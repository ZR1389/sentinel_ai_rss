
from apify_client import ApifyClient
import os
from datetime import datetime
from typing import List, Dict, Any

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
        # Actor overrides via env
        self.instagram_actor = os.getenv('APIFY_INSTAGRAM_ACTOR', 'apify/instagram-profile-scraper')
        self.twitter_actor = os.getenv('APIFY_TWITTER_ACTOR', 'apify/twitter-scraper')

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
    
    def run_twitter_scraper(self, username: str, tweets_desired: int = 20) -> Dict[str, Any]:
        """Scrape X/Twitter profile and recent tweets"""
        actor_id = self.twitter_actor
        run_input = {
            "handles": [username],
            "tweetsDesired": tweets_desired,
            "addUserInfo": True,
            "includeReplies": False,
            "includeRetweets": False,
            "start": f"https://twitter.com/{username}",
        }
        try:
            run = self.client.actor(actor_id).call(run_input=run_input)
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                return {"success": False, "platform": "twitter", "error": "No dataset id returned"}
            items = self.client.dataset(dataset_id).list_items().get("items", [])
            if not items:
                return {"success": False, "platform": "twitter", "error": "No data returned"}
            # First item usually contains tweet with embedded user info under 'user'
            profile = items[0].get("user", {})
            return {
                "success": True,
                "platform": "twitter",
                "username": username,
                "data": {
                    "profile": profile,
                    "tweets": items[:tweets_desired],
                    "scraped_at": datetime.utcnow().isoformat(),
                    "actor_used": actor_id,
                }
            }
        except Exception as e:
            return {"success": False, "platform": "twitter", "username": username, "error": str(e)}
