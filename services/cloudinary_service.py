import cloudinary
import cloudinary.uploader
import cloudinary.utils
from core.config import settings
from typing import Optional
import os

# Configure Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)


class CloudinaryService:
    """Service for handling Cloudinary uploads"""
    
    ALLOWED_FORMATS = {
        'image': ['jpg', 'jpeg', 'png'],
        'document': ['pdf']
    }
    
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    
    @staticmethod
    def get_allowed_formats_list() -> list[str]:
        """Get flat list of all allowed formats"""
        formats = []
        formats.extend(CloudinaryService.ALLOWED_FORMATS['image'])
        formats.extend(CloudinaryService.ALLOWED_FORMATS['document'])
        return formats
    
    @staticmethod
    def upload_medical_report(
        file_bytes: bytes,
        filename: str,
        patient_id: int,
        doctor_id: int
    ) -> Optional[str]:
        """
        Upload medical report to Cloudinary
        
        Args:
            file_bytes: File content in bytes
            filename: Original filename
            patient_id: Patient ID
            doctor_id: Doctor ID
            
        Returns:
            Cloudinary URL or None if upload fails
        """
        try:
            # Extract file extension
            file_extension = filename.lower().split('.')[-1]
            
            # Validate format
            if file_extension not in CloudinaryService.get_allowed_formats_list():
                raise ValueError(f"Invalid file format. Allowed: {', '.join(CloudinaryService.get_allowed_formats_list())}")
            
            # Determine resource type
            if file_extension in CloudinaryService.ALLOWED_FORMATS['image']:
                resource_type = 'image'
            else:
                resource_type = 'raw'  # For PDFs
            
            # Create unique filename
            timestamp = int(cloudinary.utils.now())
            public_id = f"medical_reports/patient_{patient_id}/doctor_{doctor_id}/{timestamp}_{filename}"
            
            # Upload to Cloudinary
            upload_result = cloudinary.uploader.upload(
                file_bytes,
                public_id=public_id,
                resource_type=resource_type,
                folder="healthcare_appointments",
                allowed_formats=CloudinaryService.get_allowed_formats_list(),
                max_file_size=CloudinaryService.MAX_FILE_SIZE,
                access_mode="public"  # Make file publicly accessible
            )

            
            return upload_result.get('secure_url')
            
        except Exception as e:
            print(f"Cloudinary upload error: {str(e)}")
            return None
    
    @staticmethod
    def delete_medical_report(url: str) -> bool:
        """
        Delete medical report from Cloudinary
        
        Args:
            url: Cloudinary URL
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            # Extract public_id from URL
            # URL format: https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/v{version}/{public_id}.{format}
            parts = url.split('/')
            
            # Find 'upload' index
            upload_index = parts.index('upload')
            
            # Get public_id (everything after version)
            public_id_with_ext = '/'.join(parts[upload_index + 2:])
            
            # Remove extension
            public_id = os.path.splitext(public_id_with_ext)[0]
            
            # Determine resource type from URL
            resource_type = 'image' if '/image/' in url else 'raw'
            
            # Delete from Cloudinary
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type
            )
            
            return result.get('result') == 'ok'
            
        except Exception as e:
            print(f"Cloudinary delete error: {str(e)}")
            return False