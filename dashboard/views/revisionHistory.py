from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from ..models.revisionHistory import RevisionHistory


@login_required
def revision_history(request):
    """Render the revision history page.

    - Shows published revisions ordered by newest first.
    - Provides `current_version`, `release_date`, and `status` for header cards.
    - Adds a `created_by_text` attribute on each revision for template compatibility.
    """
    # Query published revisions (keep as QuerySet so templates can call `.exists`)
    revisions_qs = RevisionHistory.objects.filter(is_published=True).order_by(
        "-created_at"
    )

    latest = revisions_qs.first()
    if latest:
        current_version = latest.version
        release_date = latest.effective_date or latest.created_at
        status = "Published" if latest.is_published else "Draft"
    else:
        current_version = None
        release_date = None
        status = "No releases"

    # Attach a compatibility attribute `created_by_text` used by the template
    # Prefer stored email, then user full name / username, otherwise 'System'
    for rev in revisions_qs:
        try:
            if getattr(rev, "created_by_email", None):
                rev.created_by_text = rev.created_by_email
            elif getattr(rev, "created_by", None):
                try:
                    rev.created_by_text = (
                        rev.created_by.get_full_name() or rev.created_by.username
                    )
                except Exception:
                    rev.created_by_text = str(rev.created_by)
            else:
                rev.created_by_text = "System"
        except Exception:
            rev.created_by_text = "System"

    context = {
        "revisions": revisions_qs,
        "current_version": current_version,
        "release_date": release_date,
        "status": status,
        "title": "Revision History",
    }

    return render(request, "dashboard/revision_history.html", context)
