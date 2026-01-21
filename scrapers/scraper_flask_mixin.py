"""
scraper_flask_mixin.py (FIXED PORT HANDLING)

Reusable Flask mixin based on the existing odds scraper Flask implementation.
Extracts the Flask integration pattern into a reusable component.
"""

import os
import logging
import sys
from datetime import datetime, timezone
from flask import Flask, request, jsonify
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
from typing import Dict, Any, Optional

# Fix imports for direct execution
try:
    from .scraper_base import ScraperBase  # If running as module
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from scrapers.scraper_base import ScraperBase


class ScraperFlaskMixin:
    """
    Flask mixin for scrapers based on the existing odds scraper pattern.
    
    Child classes should define:
    - scraper_name: str
    - required_params: list
    - optional_params: dict
    """
    
    # Child classes should override these
    scraper_name: str = "unknown_scraper"
    required_params: list = []
    optional_params: dict = {}
    
    def create_app(self):
        """Create Flask app for this scraper (based on existing pattern)."""
        from flask import Flask, request, jsonify
        try:
            from dotenv import load_dotenv
        except ImportError:
            load_dotenv = None
        import logging
        import sys

        app = Flask(__name__)
        if load_dotenv:
            load_dotenv()
        
        # Configure logging for Cloud Run
        if not app.debug:
            logging.basicConfig(level=logging.INFO)
        
        @app.route('/', methods=['GET'])
        @app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({
                "status": "healthy", 
                "service": "scrapers",
                "scraper": self.scraper_name,
                "version": "1.0.0",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }), 200
        
        @app.route('/scrape', methods=['POST'])
        def scrape_endpoint():
            """Main scraping endpoint (based on existing pattern)."""
            try:
                # Get parameters from JSON body or query params
                if request.is_json:
                    params = request.get_json()
                else:
                    params = request.args.to_dict()
                
                # Build scraper opts using the existing pattern
                opts = self._build_scraper_opts(params)
                
                # Validate required params
                validation_error = self._validate_scraper_params(opts)
                if validation_error:
                    return jsonify({"error": validation_error}), 400
                
                # Set debug logging
                if opts.get("debug"):
                    logging.getLogger().setLevel(logging.DEBUG)
                
                # Run the scraper (existing method)
                result = self.run(opts)
                
                if result:
                    return jsonify({
                        "status": "success",
                        "message": f"{self.scraper_name} completed successfully",
                        "scraper": self.scraper_name,
                        "run_id": self.run_id,
                        "data_summary": self.get_scraper_stats()
                    }), 200
                else:
                    return jsonify({
                        "status": "error",
                        "message": f"{self.scraper_name} failed",
                        "scraper": self.scraper_name,
                        "run_id": self.run_id
                    }), 500
                    
            except Exception as e:
                app.logger.error(f"{self.scraper_name} error: {str(e)}", exc_info=True)
                return jsonify({
                    "status": "error",
                    "scraper": self.scraper_name,
                    "message": str(e)
                }), 500
        
        return app
    
    def _build_scraper_opts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Build opts dict from request parameters (matches existing pattern)."""
        opts = {}
        
        # Add required parameters
        for param in self.required_params:
            if param in params:
                opts[param] = params[param]
        
        # Add optional parameters with defaults
        for param, default_value in self.optional_params.items():
            opts[param] = params.get(param, default_value)
        
        # Add common parameters (matches existing pattern)
        # DEFAULT TO DEV GROUP FOR LOCAL TESTING (avoids GCS issues)
        common_params = {
            "group": params.get("group", "dev"),  # Changed from "prod" to "dev"
            "run_id": params.get("run_id"),
            "debug": bool(params.get("debug", False))
        }
        opts.update(common_params)
        
        return opts
    
    def _validate_scraper_params(self, opts: Dict[str, Any]) -> Optional[str]:
        """Validate required parameters (matches existing pattern)."""
        missing_params = []
        for param in self.required_params:
            if param not in opts or opts[param] is None:
                missing_params.append(param)
        
        if missing_params:
            return f"Missing required parameter{'s' if len(missing_params) > 1 else ''}: {', '.join(missing_params)}"
        
        return None
    
    @classmethod
    def create_cli_and_flask_main(cls):
        """
        Create main function that supports both CLI and Flask modes.
        Based on the existing main entry point pattern.
        FIXED: Properly handle --port argument.
        """
        import argparse
        try:
            from dotenv import load_dotenv
        except ImportError:
            load_dotenv = None
        import logging
        import sys

        def main():
            if load_dotenv:
                load_dotenv()

            # Check if we're running as a web service or CLI
            if len(sys.argv) > 1 and sys.argv[1] == "--serve":
                # Web service mode for Cloud Run
                # Parse remaining args for port and debug
                parser = argparse.ArgumentParser()
                parser.add_argument("--serve", action="store_true")
                parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8080)))
                parser.add_argument("--debug", action="store_true")
                parser.add_argument("--host", default="0.0.0.0")
                
                args, unknown = parser.parse_known_args()
                
                app = cls().create_app()
                app.run(host=args.host, port=args.port, debug=args.debug)
            else:
                # CLI mode (existing argparse code)
                parser = argparse.ArgumentParser(description=f"Run {cls.scraper_name}")
                parser.add_argument("--serve", action="store_true", help="Start web server")
                parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8080)), help="Port for web server")
                parser.add_argument("--host", default="0.0.0.0", help="Host for web server")
                parser.add_argument("--debug", action="store_true", help="Verbose logging")
                parser.add_argument("--group", default="dev", help="exporter group")
                parser.add_argument("--run_id", help="Optional correlation ID")
                
                # Add scraper-specific required arguments
                for param in cls.required_params:
                    parser.add_argument(f"--{param}", help=f"Required parameter: {param}")
                
                # Add scraper-specific optional arguments
                for param, default in cls.optional_params.items():
                    help_text = f"Optional parameter: {param}"
                    if default is not None:
                        help_text += f" (default: {default})"
                    parser.add_argument(f"--{param}", default=default, help=help_text)
                
                args = parser.parse_args()
                
                if args.serve:
                    # Start web server with proper port handling
                    app = cls().create_app()
                    app.run(host=args.host, port=args.port, debug=args.debug)
                else:
                    # CLI scraping mode
                    
                    # Validate required params for CLI mode
                    for param in cls.required_params:
                        if not getattr(args, param):
                            parser.error(f"--{param} is required for CLI scraping")
                    
                    if args.debug:
                        logging.getLogger().setLevel(logging.DEBUG)
                        
                    # Run the scraper
                    scraper = cls()
                    scraper.run(vars(args))
        
        return main


# Utility function to convert existing Flask scrapers
def convert_existing_flask_scraper(scraper_class):
    """
    Helper function to convert existing scrapers that already have Flask integration.
    
    Usage:
        # In your existing scraper file, replace the create_app function with:
        from .scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
        
        class YourScraperClass(ScraperBase, ScraperFlaskMixin):
            scraper_name = "your_scraper"
            required_params = ["param1", "param2"] 
            optional_params = {"param3": None}
            
            # All your existing scraper methods stay the same
            
        # Replace your existing create_app() and main with:
        create_app = convert_existing_flask_scraper(YourScraperClass)
        
        if __name__ == "__main__":
            main = YourScraperClass.create_cli_and_flask_main()
            main()
    """
    def create_app():
        return scraper_class().create_app()
    
    return create_app