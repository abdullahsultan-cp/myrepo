"""SharePoint news field → Storyblok story mapping registry."""
import os as _os, sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- every pipeline folder on sys.path

EDITORIAL_PREFIXES = ("odata.", "@odata.")

# Fully mapped scalar / rich-text fields
MAPPED_FIELDS = {
    "Title": "content.title",
    "NewsSubTitle": "content.subtitle",
    "NewsSummary": "content.summary",
    "NewsContent": "content.body",
    "AlternateNewsTitle": "content.alternate_title",
    "AlternateNewsSubtitle": "content.alternate_subtitle",
    "AlternateNewsSummary": "content.alternate_summary",
    "PullQuote": "content.pull_quote",
    "PullQuoteAuthor": "content.pull_quote_author",
    "BannerCaption": "content.banner_caption",
    "MediumImageCaption": "content.medium_image_caption",
    "AlternateBannerCaption": "content.alternate_banner_caption",
    "GlobalNews": "content.global_news",
    "LocallyActive": "content.locally_active",
    "GloballyActive": "content.globally_active",
    "ScheduleStartDate": "content.schedule_start_date",
    "ScheduleEndDate": "content.schedule_end_date",
    "SequenceNumber": "content.sequence_number",
    "LocalApproverGroup": "content.local_approver_group",
    "GlobalApproverGroup": "content.global_approver_group",
    "IsPulished": "content.is_published",
    "IsGloballyApproved": "content.is_globally_approved",
    "IsLocallyApproved": "content.is_locally_approved",
    "IsModifiedByGlobal": "content.is_modified_by_global",
    "NewsInUrdu": "content.news_in_urdu",
    "Contact": "content.contact",
    "SecondaryLanguage2": "content.secondary_language_2",
    "SecondaryLanguage3": "content.secondary_language_3",
    "Id": "content.sharepoint_id",
    "ID": "content.sharepoint_id",
    "Modified": "content.sharepoint_modified",
    "Created": "content.sharepoint_created",
}

# Lookup / taxonomy fields — mapped as structured objects, not just Title
STRUCTURED_FIELDS = {
    "Category": "content.category",
    "City": "content.city",
    "Entity": "content.entity",
    "AdditionalEntity": "content.additional_entities",
    "Author": "content.author",
    "Publisher": "content.publisher",
    "ContentWriter": "content.content_writer",
    "ContentApprover": "content.content_approver",
    "Editor": "content.editor",
    "Tags": "content.tags",
}

# Story-level fields derived from item
STORY_LEVEL_FIELDS = {
    "Title": "name",
    "Tags": "tag_list",
}


def is_editorial_key(key):
    if not isinstance(key, str):
        return False
    if key.startswith(EDITORIAL_PREFIXES):
        return False
    if "@odata.navigationLinkUrl" in key:
        return False
    return True


def editorial_keys(item):
    return [key for key in item if is_editorial_key(key)]
