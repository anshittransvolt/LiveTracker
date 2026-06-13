import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings

JIRA_DOMAIN = settings.JIRA_DOMAIN
JIRA_EMAIL = settings.JIRA_EMAIL
JIRA_API_TOKEN = settings.JIRA_API_TOKEN


def create_jira_issue(
    project_key,
    summary,
    description_text,
    issue_type="Task",
    **extra_fields
):
    """
    Create Jira issue without passing creds each time.
    """

    url = f"https://{JIRA_DOMAIN}.atlassian.net/rest/api/3/issue"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # ADF description
    description_adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": description_text
                    }
                ]
            }
        ]
    }

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": description_adf,
            "issuetype": {"name": issue_type},
        }
    }

    # 🔹 Add optional fields
    payload["fields"].update(extra_fields)

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    )

    if response.status_code == 201:
        print("Issue created:", response.json().get("key"))
    else:
        print("Failed:", response.status_code, response.text)

    return response.json()