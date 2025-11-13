
from apify_client import ApifyClient
import os
from datetime import datetime

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
        self.client = ApifyClient(os.getenv('APIFY_API_TOKEN'))

    def scrape_instagram_profile(self, username):
        """
        Scrape Instagram profile using Apify
        Returns: dict with profile data
        """
        try:
            # Using popular Instagram Profile Scraper actor
            run_input = {
                "username": [username],
                "resultsLimit": 50  # posts to scrape
            }
            
            # Run the actor and wait for results
            run = self.client.actor("apify/instagram-profile-scraper").call(run_input=run_input)
            
            # Fetch results from dataset
            results = []
            for item in self.client.dataset(run["defaultDatasetId"]).iterate_items():
                results.append(item)
            
            if results:
                profile = results[0]
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
            else:
                return {"success": False, "error": "No data returned"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def scrape_linkedin_profile(self, profile_url):
        """
        Scrape LinkedIn profile
        profile_url: Full LinkedIn profile URL
        """
        try:
            run_input = {
                "profileUrls": [profile_url]
            }
            
            run = self.client.actor("apify/linkedin-profile-scraper").call(run_input=run_input)
            
            results = []
            for item in self.client.dataset(run["defaultDatasetId"]).iterate_items():
                results.append(item)
            
            if results:
                profile = results[0]
                return {
                    "success": True,
                    "platform": "linkedin",
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
            else:
                return {"success": False, "error": "No data returned"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
