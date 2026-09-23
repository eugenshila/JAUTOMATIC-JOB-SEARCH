"""Profile-grounded task categories; portals are not confirmed paid assignments."""
import re


def recommended_task_sources(profile):
    text = " ".join([profile.headline, profile.summary, *profile.skills,
                     *[" ".join([e.title, e.summary, *e.highlights]) for e in profile.experience],
                     str((profile.extra or {}).get("projects", []))]).lower()
    sources = [
        ("Data entry and web research", ("data entry", "data-entry", "research", "records"),
         "Your profile includes data capture, record keeping or research.",
         "https://www.clickworker.com/web-research-jobs/"),
        ("Product data and categorisation", ("catalogue", "catalog", "spare-parts", "spare parts", "inventory"),
         "Your product, spare-parts and inventory experience is relevant to checking and categorising data.",
         "https://www.clickworker.com/clickworker-categorization-jobs/"),
        ("Website and application testing", ("it support", "software", "application", "technical support", "testing"),
         "Your IT support or application experience is relevant to functional testing and reporting issues.",
         "https://www.utest.com/projects"),
    ]
    return [{"title": title, "reason": reason, "url": url}
            for title, terms, reason, url in sources
            if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms)]
