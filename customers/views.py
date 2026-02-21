from django.shortcuts import render
from rest_framework import viewsets, status, generics, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from .utils import generate_reset_code, send_password_reset_email, account_activation_token
from .models import Customer, Address, PasswordResetCode, ContactMessage
from .serializers import (
    CustomerSerializer, 
    UserRegistrationSerializer, 
    UserUpdateSerializer,
    ChangePasswordSerializer,
    AddressSerializer,
    PasswordResetRequestSerializer,
    PasswordResetCodeVerifySerializer,
    PasswordResetConfirmSerializer,
    ContactMessageSerializer, 
    ContactMessageAdminSerializer
)
from backend.pagination import StandardResultsSetPagination, LargeResultsSetPagination
from .tasks import send_welcome_email, send_password_reset_email_async, send_loyalty_points_notification, notify_admins_contact_message, send_contact_acknowledgement


class RegisterView(generics.CreateAPIView):
    """API endpoint for user registration"""
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # Send welcome email asynchronously using Celery
        send_welcome_email.delay(user.id)

        # Generate tokens for the new user
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': {
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
            },
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            'message': 'User registered successfully'
        }, status=status.HTTP_201_CREATED)


class LogoutView(APIView):
    """API endpoint to logout user by blacklisting refresh token"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh_token")
            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            return Response(
                {"message": "Successfully logged out"}, 
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )


class CustomerProfileView(generics.RetrieveUpdateAPIView):
    """
    API endpoint to view and update customer profile.
    No pagination needed for single profile view.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerSerializer

    def get_object(self):
        """
        Optimized query with prefetching for addresses.
        """
        return Customer.objects.select_related('user').prefetch_related(
            'addresses'
        ).get(user=self.request.user)

    def get(self, request, *args, **kwargs):
        customer = self.get_object()
        serializer = self.get_serializer(customer)
        return Response(serializer.data)


class UpdateProfileView(generics.UpdateAPIView):
    """API endpoint to update user/customer details"""
    permission_classes = [IsAuthenticated]
    serializer_class = UserUpdateSerializer

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        # Return updated customer data with prefetching
        customer = Customer.objects.select_related('user').prefetch_related(
            'addresses'
        ).get(user=instance)
        customer_serializer = CustomerSerializer(customer)
        
        return Response({
            'message': 'Profile updated successfully',
            'customer': customer_serializer.data
        })


class ChangePasswordView(generics.UpdateAPIView):
    """API endpoint to change user password"""
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({
            'message': 'Password changed successfully'
        }, status=status.HTTP_200_OK)


class AddressViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing customer addresses.
    Uses standard pagination.
    """
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        """
        Optimized query with customer prefetching.
        Filter to only show current user's addresses.
        """
        return Address.objects.filter(
            customer=self.request.user.customer
        ).select_related('customer__user').order_by('-is_default', '-created_at')

    def perform_create(self, serializer):
        """
        Create a new address.
        If set as default, unset other default addresses of the same type.
        """
        if serializer.validated_data.get('is_default', False):
            address_type = serializer.validated_data['address_type']
            Address.objects.filter(
                customer=self.request.user.customer,
                address_type=address_type
            ).update(is_default=False)
        
        serializer.save(customer=self.request.user.customer)

    def perform_update(self, serializer):
        """
        Update an address.
        If set as default, unset other default addresses of the same type.
        """
        if serializer.validated_data.get('is_default', False):
            address_type = serializer.validated_data.get(
                'address_type', 
                serializer.instance.address_type
            )
            Address.objects.filter(
                customer=self.request.user.customer,
                address_type=address_type
            ).exclude(id=serializer.instance.id).update(is_default=False)
        
        serializer.save()

    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set an address as default"""
        address = self.get_object()
        
        # Unset other default addresses of the same type
        Address.objects.filter(
            customer=request.user.customer,
            address_type=address.address_type
        ).exclude(id=address.id).update(is_default=False)
        
        address.is_default = True
        address.save()
        
        serializer = self.get_serializer(address)
        return Response(serializer.data)


class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Admin viewset for viewing all customers.
    Read-only for regular users (only their own profile).
    Uses large pagination for admin views.
    """
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    
    # Use large pagination for admin customer lists
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        """
        Optimized queryset with all necessary prefetching.
        Non-staff users can only see their own profile.
        """
        queryset = Customer.objects.select_related('user').prefetch_related('addresses')
        
        # Non-staff users can only see their own profile
        if not self.request.user.is_staff:
            return queryset.filter(user=self.request.user)
        
        # Staff users see all customers with ordering
        return queryset.order_by('-created_at')

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def add_loyalty_points(self, request, pk=None):
        """Add loyalty points to a customer (admin only)"""
        customer = self.get_object()
        points = request.data.get('points', 0)
        
        try:
            points = int(points)
            customer.loyalty_points += points
            customer.save(update_fields=['loyalty_points'])

            # Send notification asynchronously
            send_loyalty_points_notification.delay(
                customer.id,
                points,
                "Admin awarded loyalty points"
            )
            
            return Response({
                'message': f'Added {points} loyalty points',
                'total_points': customer.loyalty_points
            })
        except ValueError:
            return Response(
                {'error': 'Invalid points value'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAdminUser])
    def top_customers(self, request):
        """Get top customers by loyalty points (admin only)"""
        top_customers = self.get_queryset().order_by('-loyalty_points')[:20]
        
        # Use smaller pagination for top lists
        from backend.pagination import SmallResultsSetPagination
        paginator = SmallResultsSetPagination()
        page = paginator.paginate_queryset(top_customers, request)
        serializer = self.get_serializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

class PasswordResetRequestView(generics.GenericAPIView):
    """Request password reset email with code"""
    permission_classes = [AllowAny]
    serializer_class = PasswordResetRequestSerializer
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        print("Yo testing Me")
        
        if not serializer.is_valid():
            # Always return a success response for security
            return Response({
                "message": "If an account exists with this email, a reset code will be sent."
            }, status=status.HTTP_200_OK)
        
        user = serializer.validated_data.get('user')
        
        # Generate reset code and token
        reset_code = generate_reset_code()
        token = account_activation_token.make_token(user)
        
        # Calculate expiry time
        expires_at = timezone.now() + timezone.timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)
        
        # Create reset code record
        PasswordResetCode.objects.create(
            user=user,
            code=reset_code,
            token=token,
            expires_at=expires_at
        )
        
        # Send email asynchronously using Celery
        print(f"📝 Reset code created: {reset_code}")
        
        # Send email asynchronously using Celery
        print(f"📧 Queuing email task for user {user.id}")
        task = send_password_reset_email_async.delay(user.id, reset_code)
        print(f"✅ Task queued with ID: {task.id}")
        
        return Response({
            "message": "If an account exists with this email, a reset code will be sent."
        }, status=status.HTTP_200_OK)


class PasswordResetCodeVerifyView(generics.GenericAPIView):
    """Verify password reset code is valid"""
    permission_classes = [AllowAny]
    serializer_class = PasswordResetCodeVerifySerializer
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        return Response({
            "message": "Reset code is valid.",
            "uid": serializer.data['uid'],
            "token": serializer.data['token'],
            "code": serializer.data['code']
        }, status=status.HTTP_200_OK)


class PasswordResetConfirmView(generics.GenericAPIView):
    """Confirm password reset with code"""
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer
    
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        reset_code = serializer.validated_data['reset_code']
        new_password = serializer.validated_data['new_password']
        
        # Update user password
        user.set_password(new_password)
        user.save()
        
        # Mark reset code as used
        reset_code.mark_as_used()
        
        # Invalidate all existing refresh tokens
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
        from rest_framework_simplejwt.utils import aware_utcnow
        
        # Blacklist all outstanding tokens for this user
        tokens = OutstandingToken.objects.filter(user=user)
        for token in tokens:
            if not BlacklistedToken.objects.filter(token=token).exists():
                BlacklistedToken.objects.create(token=token, blacklisted_at=aware_utcnow())
        
        return Response({
            "message": "Password has been reset successfully. You can now log in with your new password."
        }, status=status.HTTP_200_OK)

class ContactMessageView(generics.CreateAPIView):
    """
    POST /api/contact/
    Public endpoint — anyone can submit a contact message.
    Triggers async emails to admins and sends an acknowledgement to the sender.
    """
    permission_classes = [AllowAny]
    serializer_class = ContactMessageSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Capture IP for basic spam tracking
        ip = self._get_client_ip(request)
        contact_msg = serializer.save(ip_address=ip)

        # Fire async tasks — no waiting on email sending
        notify_admins_contact_message.delay(contact_msg.id)
        send_contact_acknowledgement.delay(contact_msg.id)

        return Response(
            {"message": "Your message has been received. We'll get back to you shortly!"},
            status=status.HTTP_201_CREATED,
        )

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')


class ContactMessageAdminViewSet(viewsets.ModelViewSet):
    """
    Admin-only viewset for managing contact messages.

    GET    /api/contact/admin/          — list all messages (paginated)
    GET    /api/contact/admin/{id}/     — retrieve a single message
    PATCH  /api/contact/admin/{id}/     — update status / admin_notes
    DELETE /api/contact/admin/{id}/     — delete a message

    Supports filtering via query params:
        ?status=new|read|replied|archived
        ?search=<name or email>
    """
    serializer_class = ContactMessageAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = ContactMessage.objects.all()

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter in dict(ContactMessage.STATUS_CHOICES):
            qs = qs.filter(status=status_filter)

        # Simple search by name or email
        search = self.request.query_params.get('search')
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=search) | Q(email__icontains=search))

        return qs

    def retrieve(self, request, *args, **kwargs):
        """Auto-mark as 'read' when an admin first opens a message."""
        instance = self.get_object()
        if instance.status == 'new':
            instance.status = 'read'
            instance.save(update_fields=['status', 'updated_at'])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def mark_replied(self, request, pk=None):
        """Convenience action: POST /api/contact/admin/{id}/mark_replied/"""
        msg = self.get_object()
        msg.status = 'replied'
        msg.save(update_fields=['status', 'updated_at'])
        return Response({"message": "Marked as replied."})

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Convenience action: POST /api/contact/admin/{id}/archive/"""
        msg = self.get_object()
        msg.status = 'archived'
        msg.save(update_fields=['status', 'updated_at'])
        return Response({"message": "Message archived."})

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """GET /api/contact/admin/summary/ — count per status for dashboard badges."""
        from django.db.models import Count
        counts = (
            ContactMessage.objects
            .values('status')
            .annotate(count=Count('id'))
        )
        return Response({item['status']: item['count'] for item in counts})