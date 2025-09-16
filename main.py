"""
Job Application Agent (AI version with editable drafts)
"""

import json
from openai import OpenAI  # pip install openai
from crawler import JobScraper

# ----------------------------
# 1. Job Collector (dummy for now)
# ----------------------------

class Virgo:
    def __init__(self):
        pass

    def collect_jobs(self):
        return JobScraper().scrape('www.ariesproject.xyz')


    # ----------------------------
    # 2. GPT Cover Letter Drafting
    # ----------------------------
    client = OpenAI(api_key="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")

    def draft_cover_letter(job, resume):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",   # or "gpt-4o" / "gpt-3.5-turbo"
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Write a cover letter for this job:\n{job}\nResume:\n{resume}"}
                ]
            )
            return response.choices[0].message.content
        except Exception:
            return f"Mock Cover Letter for job {job['title']} with resume {resume[:50]}..."
    """ Check hugging face """
    # ----------------------------
    # 3. Interactive Editing
    # ----------------------------
    def review_and_edit(application):
        print("\n--- Drafted Cover Letter ---")
        print(application["cover_letter"])
        print("\nWould you like to edit this? (y/n)")
        choice = input("> ").strip().lower()

        if choice == "y":
            print("\nEnter your edited cover letter (finish with Ctrl+D / Ctrl+Z):")
            edited = []
            try:
                while True:
                    line = input()
                    edited.append(line)
            except EOFError:
                pass
            application["cover_letter"] = "\n".join(edited)

        return application


    # ----------------------------
    # 4. Save Applications
    # ----------------------------
    def save_applications(applications, filename="applications.json"):
        with open(filename, "w") as f:
            json.dump(applications, f, indent=2)
        print(f"\n✅ Saved {len(applications)} applications to {filename}")

    """ Embeddings: sentence-transformers/all-MiniLM-L6-v2 (very lightweight, good for job ↔ resume matching)

    Text generation: mistralai/Mistral-7B-Instruct or tiiuae/falcon-7b-instruct

    Summarization: facebook/bart-large-cnn """
    # ----------------------------
    # Main Agent Runner
    # ----------------------------
    """ if __name__ == "__main__":

        resume = "Python, Django, React, REST APIs, SQL, problem-solving"

        jobs = irgo.collect_jobs()
        applications = []

        for job in jobs:
            draft = draft_cover_letter(job, resume)
            application = {
                "job": job,
                "resume": resume,
                "cover_letter": draft
            }
            reviewed = review_and_edit(application)
            applications.append(reviewed)

        save_applications(applications) """
Virgo().collect_jobs()
