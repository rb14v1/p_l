from rest_framework import viewsets, permissions, generics, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from .models import Vote, Bookmark, PromptVersion, Prompt, CATEGORY_CHOICES
from .serializers import PromptSerializer, PromptVersionSerializer, UserSerializer

class IsAdminOrOwner(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.user == request.user

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserSerializer

class CategoryListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        predefined_categories = [choice[0] for choice in CATEGORY_CHOICES]
        user_categories = list(
            request.user.prompts.all()
            .values_list('category', flat=True)
            .distinct()
        )
        all_categories = sorted(list(set(predefined_categories + user_categories)))
        return Response(all_categories)

class CompanySSOView(APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, *args, **kwargs):
        sso_login_url = ""
        return Response({'sso_authorization_url': sso_login_url})

class PromoteAdminView(APIView):
    permission_classes = [permissions.IsAdminUser]
    
    def post(self, request, *args, **kwargs):
        username = request.data.get('username')
        if not username:
            return Response({'error': 'Username is required.'}, status=status.HTTP_400_BAD_REQUEST)
        user_to_promote = get_object_or_404(User, username=username)
        if user_to_promote.is_staff:
            return Response({'message': f'User "{username}" is already an admin.'}, status=status.HTTP_400_BAD_REQUEST)
        user_to_promote.is_staff = True
        user_to_promote.save()
        return Response({'message': f'Successfully promoted user "{username}" to admin.'})

class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_staff": user.is_staff,
        })

class PromptViewSet(viewsets.ModelViewSet):
    serializer_class = PromptSerializer
    queryset = Prompt.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsAdminOrOwner]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'task_type', 'output_format', 'status']
    search_fields = ['title', 'prompt_description', 'prompt_text']

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Prompt.objects.all().order_by('-created_at')

        if self.request.query_params.get('mine') == '1':
            return Prompt.objects.filter(user=user).order_by('-created_at')

        return Prompt.objects.filter(status='approved').order_by('-created_at')
    
    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            lookup_field = self.lookup_field or 'pk'
            lookup = self.kwargs.get(lookup_field)
            Model = self.queryset.model
            try:
                obj = Model.objects.get(pk=lookup)
            except Model.DoesNotExist:
                raise Http404

            user = self.request.user
            if user.is_authenticated and (user.is_staff or getattr(obj, 'user', None) == user):
                return obj
            raise Http404

    def perform_create(self, serializer):
        prompt = serializer.save(user=self.request.user)
        if prompt.status == 'approved':
            PromptVersion.objects.create(
                prompt=prompt,
                edited_by=self.request.user if self.request.user.is_authenticated else None,
                title=prompt.title,
                prompt_description=prompt.prompt_description,
                prompt_text=prompt.prompt_text,
                guidance=prompt.guidance,
                task_type=prompt.task_type,
                output_format=prompt.output_format,
                category=prompt.category
            )
    
    def perform_update(self, serializer):
        prompt_before_edit = self.get_object()
        if prompt_before_edit.status == 'approved':
            PromptVersion.objects.create(
                prompt=prompt_before_edit,
                edited_by=self.request.user,
                title=prompt_before_edit.title,
                prompt_description=prompt_before_edit.prompt_description,
                prompt_text=prompt_before_edit.prompt_text,
                guidance=prompt_before_edit.guidance,
                task_type=prompt_before_edit.task_type,
                output_format=prompt_before_edit.output_format,
                category=prompt_before_edit.category
            )
        if not self.request.user.is_staff:
            serializer.save(status='pending')
        else:
            serializer.save()

    def create(self, request, *args, **kwargs):
        existing_id = request.data.get('id') or request.data.get('pk')
        if existing_id:
            try:
                prompt = Prompt.objects.get(pk=existing_id)
            except Prompt.DoesNotExist:
                return super().create(request, *args, **kwargs)
            self.check_object_permissions(request, prompt)

            serializer = self.get_serializer(prompt, data=request.data)
            serializer.is_valid(raise_exception=True)

            prompt_before_edit = prompt
            if prompt_before_edit.status == 'approved':
                PromptVersion.objects.create(
                    prompt=prompt_before_edit,
                    edited_by=request.user,
                    title=prompt_before_edit.title,
                    prompt_description=prompt_before_edit.prompt_description,
                    prompt_text=prompt_before_edit.prompt_text,
                    guidance=prompt_before_edit.guidance,
                    task_type=prompt_before_edit.task_type,
                    output_format=prompt_before_edit.output_format,
                    category=prompt_before_edit.category
                )

            if not request.user.is_staff:
                serializer.save(status='pending')
            else:
                serializer.save()

            return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def approve(self, request, pk=None):
        prompt = self.get_object()
        if prompt.status == 'approved':
            return Response({'detail': 'Prompt is already approved.'}, status=status.HTTP_400_BAD_REQUEST)
        prompt.status = 'approved'
        prompt.save()
        return Response(PromptSerializer(prompt).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def reject(self, request, pk=None):
        prompt = self.get_object()
        if prompt.status == 'rejected':
            return Response({'detail': 'Prompt is already rejected.'}, status=status.HTTP_400_BAD_REQUEST)
        prompt.status = 'rejected'
        prompt.save()
        return Response(PromptSerializer(prompt).data)

    def _handle_vote(self, request, pk, value_to_set):
        prompt = self.get_object()
        user = request.user

        with transaction.atomic():
            existing = Vote.objects.filter(user=user, prompt=prompt).first()

            if existing is None:
                Vote.objects.create(user=user, prompt=prompt, value=value_to_set)
            else:
                if existing.value == value_to_set:
                    existing.delete()
                else:
                    existing.value = value_to_set
                    existing.save()
            prompt.refresh_from_db()
            
            likes = prompt.votes.filter(value=1).count()
            dislikes = prompt.votes.filter(value=-1).count()

            prompt.like_count = likes
            prompt.dislike_count = dislikes
            prompt.vote = likes - dislikes
            
            prompt.save(update_fields=['like_count', 'dislike_count', 'vote'])

        serializer = PromptSerializer(prompt, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def upvote(self, request, pk=None):
        return self._handle_vote(request, pk, value_to_set=1)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def downvote(self, request, pk=None):
        return self._handle_vote(request, pk, value_to_set=-1)
    
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def history(self, request, pk=None):
        prompt = self.get_object()
        if not request.user.is_staff and prompt.user != request.user:
            return Response(
                {'detail': 'You do not have permission to view this history.'},
                status=status.HTTP_403_FORBIDDEN
            )
        versions = prompt.versions.all()
        serializer = PromptVersionSerializer(versions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminOrOwner], url_path='revert/(?P<version_id>\\d+)')
    def revert(self, request, pk=None, version_id=None):
        
        prompt = self.get_object()
        version = get_object_or_404(PromptVersion, pk=version_id)

        if version.prompt != prompt:
            return Response(
                {'error': 'Version does not belong to this prompt.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if prompt.status == 'approved':
            PromptVersion.objects.create(
                prompt=prompt,
                edited_by=request.user,
                title=prompt.title,
                prompt_description=prompt.prompt_description,
                prompt_text=prompt.prompt_text,
                guidance=prompt.guidance,
                task_type=prompt.task_type,
                output_format=prompt.output_format,
                category=prompt.category
            )
        
        prompt.title = version.title
        prompt.prompt_description = version.prompt_description
        prompt.prompt_text = version.prompt_text
        prompt.guidance = version.guidance
        prompt.task_type = version.task_type
        prompt.output_format = version.output_format
        prompt.category = version.category
        
        if not request.user.is_staff:
            prompt.status = 'pending'
        
        prompt.save()
        
        serializer = self.get_serializer(prompt)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BookmarkToggleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, *args, **kwargs):
        prompt = get_object_or_404(Prompt, pk=pk)
        user = request.user
        existing = prompt.bookmarks.filter(user=user).first()
        if existing is None:
            Bookmark.objects.create(user=user, prompt=prompt)
        else:
            existing.delete()

        serializer = PromptSerializer(prompt, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
