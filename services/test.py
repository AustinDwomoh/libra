import requests
from .config import Config

API_KEY = Config.J_SEARCH_API_KEY  # set this in your .env or env vars
  # or the documented endpoint

def search_jobs(query: str, location: str = "", page: int = 1):
    params = {
        "query": query,
        "location": location,
        "page": page,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }

    resp = requests.get(Config.JSEARCH_API_URL, params=params, headers=headers)
    return resp.json()  # typically contains a list of jobs + metadata

if __name__ == "__main__":
    #jobs = search_jobs("software engineer", "Chicago, IL", page=1)
    #print("Jobs found:", len(jobs.get("data", [])))
    #for job in jobs.get("data", []):  # or .get("jobs") — depends on wrapper
    #    print(job.get("job_title"), "-", job.get("employer_name"))
    #    print("Apply:", job.get("job_apply_link"))
    #    print("---")
    
    print(requests.get("https://prescient.com/", headers={"User-Agent": "Mozilla/5.0"}).json())