"""
Asset Upload and Management Views for SENTINEL
"""
import os
import uuid
from datetime import datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from core.hashing import generate_file_hash
from core.mongodb import get_asset_manager


class AssetUploadView(APIView):
    """Asset Upload View - JWT Authentication Required"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Upload asset file (video/image) and store metadata in MongoDB
        """
        try:
            # Check if file is present
            if 'file' not in request.FILES:
                return Response(
                    {'error': 'No file provided'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            file_obj = request.FILES['file']
            
            # Validate file
            validation_error = self._validate_file(file_obj)
            if validation_error:
                return Response(validation_error, status=status.HTTP_400_BAD_REQUEST)
            
            # Generate unique filename
            file_extension = os.path.splitext(file_obj.name)[1].lower()
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            
            # Create upload directory if it doesn't exist
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'videos')
            os.makedirs(upload_dir, exist_ok=True)
            
            # Save file
            file_path = os.path.join(upload_dir, unique_filename)
            with open(file_path, 'wb') as destination:
                for chunk in file_obj.chunks():
                    destination.write(chunk)
            
            # Generate file hash
            with open(file_path, 'rb') as f:
                file_hash = generate_file_hash(f)
            
            # Check if file with same hash already exists
            asset_manager = get_asset_manager()
            existing_asset = asset_manager.get_asset_by_hash(file_hash)
            if existing_asset:
                # Remove uploaded file as it's a duplicate
                os.remove(file_path)
                return Response(
                    {
                        'message': 'File already exists',
                        'asset_id': existing_asset['_id'],
                        'file_hash': file_hash,
                        'duplicate': True
                    },
                    status=status.HTTP_200_OK
                )
            
            # Prepare asset metadata
            asset_data = {
                'user_id': str(request.user.id),
                'file_name': file_obj.name,
                'file_path': f"/media/videos/{unique_filename}",
                'file_hash': file_hash,
                'uploaded_at': datetime.utcnow(),
                'metadata': {
                    'size': file_obj.size,
                    'content_type': file_obj.content_type,
                    'original_name': file_obj.name
                },
                'fingerprints': {
                    'phash': None,
                    'dhash': None,
                    'video': None
                }
            }
            
            # Store in MongoDB
            asset_id = asset_manager.insert_asset(asset_data)
            
            return Response(
                {
                    'message': 'Upload successful',
                    'asset_id': asset_id,
                    'file_hash': file_hash,
                    'file_path': asset_data['file_path'],
                    'metadata': asset_data['metadata']
                },
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            return Response(
                {'error': f'Upload failed: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _validate_file(self, file_obj: UploadedFile) -> dict:
        """
        Validate uploaded file
        
        Returns:
            Error dict if validation fails, None if valid
        """
        # Check file size
        max_size = getattr(settings, 'MAX_FILE_SIZE', 50 * 1024 * 1024)  # 50MB
        if file_obj.size > max_size:
            return {
                'error': 'File too large',
                'max_size': f"{max_size // (1024 * 1024)}MB",
                'file_size': f"{file_obj.size // (1024 * 1024)}MB"
            }
        
        # Check file type
        allowed_types = getattr(settings, 'ALLOWED_FILE_TYPES', ['mp4', 'jpg', 'jpeg', 'png'])
        file_extension = os.path.splitext(file_obj.name)[1].lower().lstrip('.')
        
        if file_extension not in allowed_types:
            return {
                'error': 'File type not allowed',
                'allowed_types': allowed_types,
                'file_type': file_extension
            }
        
        return None


class AssetListView(APIView):
    """List user's uploaded assets"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get list of assets for the authenticated user
        """
        try:
            # Get query parameters
            page = int(request.GET.get('page', 1))
            limit = int(request.GET.get('limit', 20))
            skip = (page - 1) * limit
            
            # Fetch assets
            asset_manager = get_asset_manager()
            assets = asset_manager.get_assets(
                user_id=str(request.user.id),
                limit=limit,
                skip=skip
            )
            
            return Response(
                {
                    'assets': assets,
                    'page': page,
                    'limit': limit,
                    'total': len(assets)
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            return Response(
                {'error': f'Failed to fetch assets: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AssetDetailView(APIView):
    """Get details of a specific asset"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, asset_id: str):
        """
        Get asset details by ID
        """
        try:
            asset_manager = get_asset_manager()
            asset = asset_manager.get_asset_by_id(asset_id)
            
            if not asset:
                return Response(
                    {'error': 'Asset not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check if asset belongs to the user
            if asset['user_id'] != str(request.user.id):
                return Response(
                    {'error': 'Access denied'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            return Response(asset, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': f'Failed to fetch asset: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, asset_id: str):
        """
        Delete an asset
        """
        try:
            asset_manager = get_asset_manager()
            asset = asset_manager.get_asset_by_id(asset_id)
            
            if not asset:
                return Response(
                    {'error': 'Asset not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check if asset belongs to the user
            if asset['user_id'] != str(request.user.id):
                return Response(
                    {'error': 'Access denied'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Delete file from filesystem
            file_path = os.path.join(settings.MEDIA_ROOT, asset['file_path'].lstrip('/media/'))
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # Delete from MongoDB
            success = asset_manager.delete_asset(asset_id)
            
            if success:
                return Response(
                    {'message': 'Asset deleted successfully'}, 
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {'error': 'Failed to delete asset'}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            return Response(
                {'error': f'Failed to delete asset: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
