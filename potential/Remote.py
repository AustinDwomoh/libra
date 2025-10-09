#class RemoteOKHelper:
#    """Helper class for RemoteOK API integration"""
#    
#    def __init__(self):
#        self.headers = {
#            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
#        }
#    
#    def fetch_jobs(self, position_type: str = "intern") -> List[Dict]:
#        """
#        Main method: Fetch jobs from RemoteOK API
#        
#        Args:
#            position_type: "intern", "fulltime", or "both"
#        """
#        logger.info(f"RemoteOK: Fetching {position_type} jobs...")
#        
#        try:
#            response = requests.get(
#                Config.REMOTEOK_API_URL,
#                headers=self.headers,
#                timeout=Config.REQUEST_TIMEOUT
#            )
#            response.raise_for_status()
#            
#            jobs = response.json()[1:]  # Skip metadata at index 0
#            
#            # Filter based on position type
#            relevant_jobs = [
#                self._map_job(job) for job in jobs
#                if self._is_relevant_job(job, position_type)
#            ]
#            
#            logger.info(f"RemoteOK: Found {len(relevant_jobs)} relevant jobs")
#            return relevant_jobs
#            
#        except requests.RequestException as e:
#            logger.error(f"RemoteOK API error: {e}")
#            return []
#    
#    def _is_relevant_job(self, job: Dict, position_type: str = "intern") -> bool:
#        """Check if job matches the requested position type"""
#        position = job.get("position", "").lower()
#        tags = [t.lower() for t in job.get("tags", [])]
#        
#        # Internship keywords
#        internship_keywords = ["intern", "internship"]
#        is_internship = any(kw in position or kw in tags for kw in internship_keywords)
#        
#        # Entry-level/Junior keywords
#        entry_keywords = ["entry level", "junior", "graduate", "new grad"]
#        is_entry = any(kw in position for kw in entry_keywords)
#        
#        # Relevant tech roles
#        relevant_keywords = ["frontend", "backend", "fullstack", "data", "software", 
#                           "web", "developer", "engineer", "designer", "analyst"]
#        is_relevant_tech = any(kw in position or kw in tags for kw in relevant_keywords)
#        
#        # Filter based on position_type
#        if position_type == "intern":
#            return is_internship and is_relevant_tech
#        elif position_type == "fulltime":
#            return (is_entry or is_relevant_tech) and not is_internship
#        else:  # both
#            return is_relevant_tech and (is_internship or is_entry or True)
#    
#    def _map_job(self, job: Dict) -> Dict:
#        """Map RemoteOK response to standard job format"""
#        # Determine position type
#        position = job.get("position", "").lower()
#        tags = [t.lower() for t in job.get("tags", [])]
#        
#        if any(kw in position or kw in tags for kw in ["intern", "internship"]):
#            position_type = "internship"
#        else:
#            position_type = "fulltime"
#        
#        return {
#            "company": job.get("company", ""),
#            "title": job.get("position", ""),
#            "location": "Remote",
#            "link": job.get("url", ""),
#            "source": "remoteok",
#            "date_posted": job.get("date"),
#            "description": job.get("description"),
#            "remote": True,
#            "tags": job.get("tags", []),
#            "sponsorship": None,
#            "position_type": position_type
#        }