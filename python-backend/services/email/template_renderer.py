"""
Jinja2 email template renderer.

Renders email templates from files or database-stored strings.
Reuses the same custom filters as the PDF report formatter via shared utils.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader, BaseLoader, select_autoescape

from utils.jinja_filters import register_filters

logger = logging.getLogger(__name__)

# Template directory for file-based templates
TEMPLATES_DIR = Path(__file__).parent / "templates"


class EmailTemplateRenderer:
    """
    Renders Jinja2 email templates.

    Supports two modes:
    - File-based templates from services/email/templates/
    - String-based templates stored in the email_template database table
    """

    def __init__(self):
        # File-based environment
        self._file_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        register_filters(self._file_env)

        # String-based environment (for DB-stored templates)
        self._string_env = Environment(
            loader=BaseLoader(),
            autoescape=select_autoescape(["html", "xml"]),
        )
        register_filters(self._string_env)

    def render_file_template(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Render a file-based template.

        Args:
            template_name: Template filename (e.g., 'invoice_reminder.html')
            context: Template variables

        Returns:
            Rendered HTML string
        """
        template = self._file_env.get_template(template_name)
        return template.render(**context)

    def render_string_template(
        self,
        template_string: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Render a string-based template (from database).

        Args:
            template_string: Jinja2 template string
            context: Template variables

        Returns:
            Rendered string
        """
        template = self._string_env.from_string(template_string)
        return template.render(**context)

    def render_email(
        self,
        subject_template: str,
        body_html_template: str,
        body_text_template: Optional[str],
        context: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Render a complete email (subject + body).

        Args:
            subject_template: Jinja2 subject line template
            body_html_template: Jinja2 HTML body template
            body_text_template: Optional Jinja2 text body template
            context: Template variables

        Returns:
            Dict with 'subject', 'html', and optionally 'text'
        """
        result = {
            "subject": self.render_string_template(subject_template, context),
            "html": self.render_string_template(body_html_template, context),
        }

        if body_text_template:
            result["text"] = self.render_string_template(body_text_template, context)

        return result

