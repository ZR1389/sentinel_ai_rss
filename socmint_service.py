
from apify_client import ApifyClient
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

class SocmintService:
    def save_socmint_data(self, user_id, platform, username, data):
        """Save scraped data to Postgres"""
        from app.models import db
        import json
        from datetime import datetime
        query = """
            INSERT INTO socmint_profiles (user_id, platform, username, data, scraped_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """
        cursor = db.execute(query, (user_id, platform, username, json.dumps(data), datetime.utcnow()))
        db.commit()
        return cursor.fetchone()[0]

    def __init__(self):
        token = os.getenv('APIFY_API_TOKEN')
        if not token:
            raise RuntimeError("APIFY_API_TOKEN not set")
        self.client = ApifyClient(token)
        # Allow actor overrides via env for flexibility / rotation
        self.instagram_actor = os.getenv('APIFY_INSTAGRAM_ACTOR', 'apify/instagram-profile-scraper')
        # Provide a fallback chain for LinkedIn where official actors periodically break
        # Ordered list; first that returns data wins.
        self.linkedin_actor_chain: List[str] = [
            os.getenv('APIFY_LINKEDIN_ACTOR', 'apify/linkedin-profile-scraper'),
            'apify/linkedin-profile-scraper-lite',            # hypothetical lighter variant
            'jupri/linkdin-scraper',                          # community actor (name often misspelled intentionally)
        ]

    def _run_actor(self, actor_id: str, run_input: Dict[str, Any]) -> Dict[str, Any]:
        """Helper: run an actor and return {'success': bool, 'run': run, 'items': [...], 'error': str?}"""
        try:
            run = self.client.actor(actor_id).call(run_input=run_input)
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                return {"success": False, "error": "No dataset id returned", "items": []}
            items: List[Dict[str, Any]] = []
            for item in self.client.dataset(dataset_id).iterate_items():
                items.append(item)
            if not items:
                return {"success": False, "error": "Dataset empty", "items": []}
            return {"success": True, "run": run, "items": items}
        except Exception as e:
            return {"success": False, "error": str(e), "items": []}

    def scrape_instagram_profile(self, username: str) -> Dict[str, Any]:
        """
        Scrape Instagram profile using Apify
        Returns: dict with profile data
        """
        try:
            # Using popular Instagram Profile Scraper actor
            # Correct key expected by most Instagram actors is 'usernames'
            run_input = {
                "usernames": [username],
                "resultsLimit": 50,
            }
            result = self._run_actor(self.instagram_actor, run_input)
            if not result.get("success"):
                return {"success": False, "platform": "instagram", "username": username, "error": result.get("error", "Unknown error")}
            profile = result["items"][0]
            return {
                "success": True,
                "platform": "instagram",
                "username": username,
                "data": {
                    "full_name": profile.get("fullName"),
                    "bio": profile.get("biography"),
                    "followers": profile.get("followersCount"),
                    "following": profile.get("followsCount"),
                    "posts_count": profile.get("postsCount"),
                    "is_verified": profile.get("verified"),
                    "is_private": profile.get("private"),
                    "profile_pic_url": profile.get("profilePicUrl"),
                    "recent_posts": profile.get("latestPosts", [])[:10],  # Last 10 posts
                    "scraped_at": datetime.utcnow().isoformat()
                }
            }
                
        except Exception as e:
            return {"success": False, "platform": "instagram", "username": username, "error": str(e)}
    
    def scrape_linkedin_profile(self, profile_url: str) -> Dict[str, Any]:
        """
        Scrape LinkedIn profile
        profile_url: Full LinkedIn profile URL
        """
        try:
            run_input = {"profileUrls": [profile_url]}
            last_error: Optional[str] = None
            items: List[Dict[str, Any]] = []
            used_actor: Optional[str] = None
            for actor_id in self.linkedin_actor_chain:
                result = self._run_actor(actor_id, run_input)
                if result.get("success"):
                    items = result["items"]
                    used_actor = actor_id
                    break
                last_error = result.get("error")
            if items:
                profile = items[0]
                return {
                    "success": True,
                    "platform": "linkedin",
                    "actor_used": used_actor,
                    "data": {
                        "name": profile.get("name"),
                        "headline": profile.get("headline"),
                        "location": profile.get("location"),
                        "connections": profile.get("connectionsCount"),
                        "current_company": profile.get("positions", [{}])[0].get("companyName") if profile.get("positions") else None,
                        "positions": profile.get("positions", [])[:3],  # Last 3 jobs
                        "education": profile.get("education", []),
                        "skills": profile.get("skills", [])[:10],
                        "profile_url": profile_url,
                        "scraped_at": datetime.utcnow().isoformat()
                    }
                }
            return {"success": False, "platform": "linkedin", "error": last_error or "No data returned"}
        except Exception as e:
            return {"success": False, "platform": "linkedin", "error": str(e)}
