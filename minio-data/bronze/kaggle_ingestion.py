"""
Bronze Layer - Kaggle Data Ingestion
Author: Afnan Khan
Description: Downloads Olist E-Commerce dataset from Kaggle and uploads to MinIO bronze bucket
"""

import os
import zipfile
import pandas as pd
from minio import Minio
from minio.error import S3Error
import kaggle
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KaggleDataIngestion:
    def __init__(self):
        # MinIO configuration
        self.minio_client = Minio(
            "minio:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False
        )
        self.bucket_name = "bronze"
        self.dataset_name = "olistbr/brazilian-ecommerce"
        
    def setup_minio_bucket(self):
        """Create bronze bucket if it doesn't exist"""
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
            else:
                logger.info(f"Bucket {self.bucket_name} already exists")
        except S3Error as e:
            logger.error(f"Error creating bucket: {e}")
            raise
    
    def download_kaggle_dataset(self):
        """Download Olist dataset from Kaggle"""
        try:
            # Set Kaggle credentials
            os.environ['KAGGLE_CONFIG_DIR'] = '.'
            
            # Download dataset
            logger.info(f"Downloading dataset: {self.dataset_name}")
            kaggle.api.dataset_download_files(
                self.dataset_name,
                path='/tmp/temp_data',
                unzip=True
            )
            logger.info("Dataset downloaded successfully")
            
        except Exception as e:
            logger.error(f"Error downloading dataset: {e}")
            raise
    
    def upload_csv_files_to_minio(self):
        """Upload all CSV files to MinIO bronze bucket"""
        try:
            data_folder = '/tmp/temp_data'
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Get all CSV files
            csv_files = [f for f in os.listdir(data_folder) if f.endswith('.csv')]
            
            for csv_file in csv_files:
                local_path = os.path.join(data_folder, csv_file)
                # Create object name with timestamp for versioning
                object_name = f"kaggle_data/{timestamp}/{csv_file}"
                
                # Upload to MinIO
                self.minio_client.fput_object(
                    self.bucket_name,
                    object_name,
                    local_path
                )
                logger.info(f"Uploaded {csv_file} to {object_name}")
                
        except Exception as e:
            logger.error(f"Error uploading files to MinIO: {e}")
            raise
    
    def cleanup_temp_files(self):
        """Clean up temporary downloaded files"""
        try:
            import shutil
            if os.path.exists('/tmp/temp_data'):
                shutil.rmtree('/tmp/temp_data')
                logger.info("Cleaned up temporary files")
        except Exception as e:
            logger.error(f"Error cleaning up temp files: {e}")
    
    def run_ingestion(self):
        """Main method to run the complete ingestion process"""
        try:
            logger.info("Starting Kaggle data ingestion process")
            
            # Setup MinIO bucket
            self.setup_minio_bucket()
            
            # Download dataset from Kaggle
            self.download_kaggle_dataset()
            
            # Upload CSV files to MinIO
            self.upload_csv_files_to_minio()
            
            # Cleanup temporary files
            self.cleanup_temp_files()
            
            logger.info("Kaggle data ingestion completed successfully")
            
        except Exception as e:
            logger.error(f"Ingestion process failed: {e}")
            # Cleanup on failure
            self.cleanup_temp_files()
            raise

if __name__ == "__main__":
    ingestion = KaggleDataIngestion()
    ingestion.run_ingestion()