"""Minimal placeholder email copy. Content/product copy is a frontend/product
refinement pass later (per the build brief: "template rendering content can
be minimal/placeholder copy for now"). All user-facing strings say Rowan
per CLAUDE.md naming rules even in placeholder form.

Templates: first_outreach, follow_up, revision_request, handled_notice,
escalation_notice (vendor-facing: first two + revision_request; PM-facing:
handled_notice + escalation_notice).
"""

from __future__ import annotations

TEMPLATE_SUBJECTS = {
    "first_outreach": "Time to renew your Certificate of Insurance — {vendor_name}",
    "follow_up": "Reminder: Certificate of Insurance renewal — {vendor_name}",
    "revision_request": "Action needed: updated Certificate of Insurance — {vendor_name}",
    "handled_notice": "Rowan: COI renewed for {vendor_name}",
    "escalation_notice": "Rowan needs your attention: {vendor_name}",
}


def render(template_id: str, template_vars: dict[str, str]) -> tuple[str, str]:
    """Returns (subject, html_body). Placeholder copy — swap for real
    product copy later without touching the send path."""
    subject_template = TEMPLATE_SUBJECTS.get(template_id, "Rowan notice — {vendor_name}")
    subject = subject_template.format(**{**{"vendor_name": ""}, **template_vars})

    if template_id == "first_outreach":
        body = (
            f"<p>Hi {template_vars.get('vendor_name', 'there')},</p>"
            f"<p>Your certificate of insurance on file is approaching its expiration date. "
            f"Please reply to this email with your updated certificate of insurance "
            f"(PDF, PNG, JPG, or TIFF) so we can keep your records current.</p>"
            f"<p>Thanks,<br/>Rowan, on behalf of {template_vars.get('org_name', 'your property manager')}</p>"
        )
    elif template_id == "follow_up":
        body = (
            f"<p>Hi {template_vars.get('vendor_name', 'there')},</p>"
            f"<p>Just a reminder — we still need your updated certificate of insurance. "
            f"Please reply with the current document at your earliest convenience.</p>"
            f"<p>Thanks,<br/>Rowan</p>"
        )
    elif template_id == "revision_request":
        body = (
            f"<p>Hi {template_vars.get('vendor_name', 'there')},</p>"
            f"<p>We reviewed the certificate you sent, and it needs a revision: "
            f"{template_vars.get('revision_reason', 'please see below')}.</p>"
            f"<p>Please reply with an updated certificate.</p>"
            f"<p>Thanks,<br/>Rowan</p>"
        )
    elif template_id == "handled_notice":
        body = (
            f"<p>Rowan renewed the certificate of insurance for "
            f"{template_vars.get('vendor_name', 'this vendor')} — "
            f"valid through {template_vars.get('valid_to', 'TBD')} — filed.</p>"
        )
    elif template_id == "escalation_notice":
        body = (
            f"<p>Rowan flagged something that needs your review for "
            f"{template_vars.get('vendor_name', 'this vendor')}: "
            f"{template_vars.get('summary', 'see the run trace for details')}.</p>"
        )
    else:
        body = f"<p>{template_vars}</p>"

    return subject, body
