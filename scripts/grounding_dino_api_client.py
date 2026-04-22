#!/usr/bin/env python3

"""
GroundingDINO REST API Client

A Python client for interacting with the GroundingDINO web service.

Usage:
    python grounding_dino_api_client.py --image path/to/image.jpg --prompt "person . car . dog"
"""

import requests
import base64
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class GroundingDINOClient:
    """Client for GroundingDINO REST API"""
    
    def __init__(self, base_url: str = "http://192.168.0.232:5000"):
        """
        Initialize the API client.
        
        Args:
            base_url: Base URL of the GroundingDINO service
        """
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
    
    def health_check(self) -> Dict:
        """
        Check if the service is healthy and GPU is available.
        
        Returns:
            Dictionary with health status
        """
        response = self.session.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()
    
    def get_model_info(self) -> Dict:
        """
        Get information about the loaded model.
        
        Returns:
            Dictionary with model information
        """
        response = self.session.get(f"{self.base_url}/api/info")
        response.raise_for_status()
        return response.json()
    
    def detect_objects_from_file(
        self,
        image_path: str,
        text_prompt: str = "all objects",
        box_threshold: float = 0.35,
        text_threshold: float = 0.25
    ) -> Dict:
        """
        Detect objects in an image using file upload.
        
        Args:
            image_path: Path to the image file
            text_prompt: Object descriptions separated by dots (e.g., "person . car . dog")
            box_threshold: Detection confidence threshold (0-1)
            text_threshold: Text matching threshold (0-1)
        
        Returns:
            Dictionary with detection results
        """
        if not Path(image_path).exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        with open(image_path, 'rb') as f:
            files = {'file': (Path(image_path).name, f, 'image/jpeg')}
            data = {
                'text_prompt': text_prompt,
                'box_threshold': box_threshold,
                'text_threshold': text_threshold
            }
            response = self.session.post(
                f"{self.base_url}/api/predict",
                files=files,
                data=data
            )
        
        response.raise_for_status()
        return response.json()
    
    def detect_objects_from_base64(
        self,
        image_path: str,
        text_prompt: str = "all objects",
        box_threshold: float = 0.35,
        text_threshold: float = 0.25
    ) -> Dict:
        """
        Detect objects using base64-encoded image.
        
        Args:
            image_path: Path to the image file
            text_prompt: Object descriptions separated by dots
            box_threshold: Detection confidence threshold (0-1)
            text_threshold: Text matching threshold (0-1)
        
        Returns:
            Dictionary with detection results
        """
        if not Path(image_path).exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        # Encode image to base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        payload = {
            'image': image_data,
            'text_prompt': text_prompt,
            'box_threshold': box_threshold,
            'text_threshold': text_threshold
        }
        
        response = self.session.post(
            f"{self.base_url}/api/predict",
            json=payload
        )
        
        response.raise_for_status()
        return response.json()
    
    def save_annotated_image(self, result: Dict, output_path: str) -> None:
        """
        Save the annotated image from detection result.
        
        Args:
            result: Detection result dictionary
            output_path: Path where to save the annotated image
        """
        if 'annotated_image' not in result:
            raise ValueError("No annotated image in result")
        
        # Decode base64 image
        image_data = base64.b64decode(result['annotated_image'])
        
        # Save to file
        with open(output_path, 'wb') as f:
            f.write(image_data)
        
        print(f"✅ Annotated image saved to: {output_path}")
    
    def download_result_image(self, result_url: str, output_path: str) -> None:
        """
        Download the result image from the server.
        
        Args:
            result_url: URL path to the result image (from API response)
            output_path: Path where to save the image
        """
        response = self.session.get(f"{self.base_url}{result_url}")
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        print(f"✅ Result image downloaded to: {output_path}")
    
    def print_results(self, result: Dict) -> None:
        """
        Pretty print the detection results.
        
        Args:
            result: Detection result dictionary
        """
        if not result.get('success', False):
            print("❌ Detection failed")
            return
        
        predictions = result['predictions']
        count = predictions['count']
        
        print(f"\n{'='*60}")
        print(f"🎯 Detection Results: {count} object(s) found")
        print(f"{'='*60}\n")
        
        if count == 0:
            print("No objects detected. Try adjusting the thresholds.")
            return
        
        # Print each detected object
        for idx, (phrase, logit, box) in enumerate(zip(
            predictions['phrases'],
            predictions['logits'],
            predictions['boxes']
        ), 1):
            confidence = logit * 100
            print(f"{idx}. {phrase}")
            print(f"   Confidence: {confidence:.2f}%")
            print(f"   Bounding Box: [{box[0]:.3f}, {box[1]:.3f}, {box[2]:.3f}, {box[3]:.3f}]")
            print()


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(
        description="GroundingDINO REST API Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Detect objects with default settings
  python grounding_dino_api_client.py --image photo.jpg --prompt "person . car . dog"
  
  # Adjust thresholds
  python grounding_dino_api_client.py --image photo.jpg --prompt "cat . dog" --box-threshold 0.5
  
  # Save annotated image
  python grounding_dino_api_client.py --image photo.jpg --prompt "person" --output result.jpg
  
  # Use base64 encoding
  python grounding_dino_api_client.py --image photo.jpg --prompt "person" --use-base64
  
  # Check service health
  python grounding_dino_api_client.py --health
  
  # Get model info
  python grounding_dino_api_client.py --info
  
  # Geological/Planetary detection examples
  python grounding_dino_api_client.py --image mars_surface.jpg --prompt "rock . boulder . crater . regolith"
  python grounding_dino_api_client.py --image lunar_site.jpg --prompt "crater . shadow . debris . dust"
        """
    )
    
    parser.add_argument(
        '--url',
        default='http://192.168.0.232:5000',
        help='Base URL of the GroundingDINO service (default: http://192.168.0.232:5000)'
    )
    
    parser.add_argument(
        '--image',
        help='Path to the image file'
    )
    
    parser.add_argument(
        '--prompt',
        default='person . car . dog . cat',
        help='Text prompt for object detection (default: "person . car . dog . cat")'
    )
    
    parser.add_argument(
        '--box-threshold',
        type=float,
        default=0.35,
        help='Box confidence threshold (0-1, default: 0.35)'
    )
    
    parser.add_argument(
        '--text-threshold',
        type=float,
        default=0.25,
        help='Text matching threshold (0-1, default: 0.25)'
    )
    
    parser.add_argument(
        '--output',
        help='Path to save the annotated image'
    )
    
    parser.add_argument(
        '--use-base64',
        action='store_true',
        help='Use base64 encoding instead of file upload'
    )
    
    parser.add_argument(
        '--health',
        action='store_true',
        help='Check service health'
    )
    
    parser.add_argument(
        '--info',
        action='store_true',
        help='Get model information'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    
    args = parser.parse_args()
    
    # Create client
    client = GroundingDINOClient(base_url=args.url)
    
    try:
        # Health check
        if args.health:
            health = client.health_check()
            if args.json:
                print(json.dumps(health, indent=2))
            else:
                print(f"\n🏥 Service Health Check")
                print(f"{'='*60}")
                print(f"Status: {health['status']}")
                print(f"Device: {health['device']}")
                print(f"CUDA Available: {health['cuda_available']}")
            return
        
        # Model info
        if args.info:
            info = client.get_model_info()
            if args.json:
                print(json.dumps(info, indent=2))
            else:
                print(f"\nℹ️  Model Information")
                print(f"{'='*60}")
                print(f"Model: {info['model']}")
                print(f"Config: {info['config']}")
                print(f"Checkpoint: {info['checkpoint']}")
                print(f"Device: {info['device']}")
                print(f"Supported Formats: {', '.join(info['supported_formats'])}")
                print(f"Max File Size: {info['max_file_size_mb']} MB")
            return
        
        # Require image for detection
        if not args.image:
            parser.error("--image is required for object detection")
        
        # Perform detection
        print(f"\n🔍 Processing image: {args.image}")
        print(f"📝 Text prompt: {args.prompt}")
        print(f"⚙️  Box threshold: {args.box_threshold}")
        print(f"⚙️  Text threshold: {args.text_threshold}")
        
        if args.use_base64:
            print("📦 Using base64 encoding...")
            result = client.detect_objects_from_base64(
                args.image,
                args.prompt,
                args.box_threshold,
                args.text_threshold
            )
        else:
            print("📤 Uploading file...")
            result = client.detect_objects_from_file(
                args.image,
                args.prompt,
                args.box_threshold,
                args.text_threshold
            )
        
        # Output results
        if args.json:
            # Remove base64 image from JSON output (too large)
            result_copy = result.copy()
            if 'annotated_image' in result_copy:
                result_copy['annotated_image'] = '<base64_data_removed>'
            print(json.dumps(result_copy, indent=2))
        else:
            client.print_results(result)
        
        # Save annotated image
        if args.output:
            client.save_annotated_image(result, args.output)
        elif not args.json:
            # Auto-save if not in JSON mode and no output specified
            output_path = Path(args.image).stem + "_annotated.jpg"
            client.save_annotated_image(result, output_path)
    
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Cannot connect to {args.url}")
        print("   Make sure the GroundingDINO service is running.")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        if e.response is not None:
            try:
                error_data = e.response.json()
                print(f"   {error_data.get('error', 'Unknown error')}")
            except:
                pass
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

