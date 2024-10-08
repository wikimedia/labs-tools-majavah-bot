import logging
from re import compile

from pywikibot import Page

from majavahbot.api import MediawikiApi, ReplicaDatabase, get_mediawiki_api, manual_run
from majavahbot.tasks import Task, task_registry

LOGGER = logging.getLogger(__name__)

ENTRY_REGEX = compile(r"\n:*\*+ ?([^\n]+)")
LOCAL_LINK_REGEX = compile(r"\[\[([^\:\]]+)\]\]")
OTHER_WIKI_LINK_REGEX = compile(r"\[\[:?([a-z]{2,3}):([^\:|\]]+)(\|[^:\]]+)?\]\]")

EXISTING_PAGE_QUERY = """
SELECT page_title FROM page
WHERE page_namespace = 0
AND page_is_redirect = 0
AND page_title IN ({})
AND NOT EXISTS (SELECT cl_from FROM categorylinks WHERE cl_from = page.page_id AND cl_to IN ("Täsmennyssivut", "Pikapoisto"))
AND EXISTS (SELECT fp_page_id FROM flaggedpages WHERE fp_page_id = page.page_id AND fp_reviewed = 1)
"""


class FiwikiRequestedArticlesTask(Task):
    def __init__(self, task_id: str, name: str, site: str, family: str) -> None:
        super().__init__(task_id, name, site, family)
        self.register_task_configuration(
            "Käyttäjä:MajavahBot/Asetukset/Artikkelitoiveiden siivoaja"
        )
        self.supports_manual_run = True

    def compare_wikidata_qs(self, page: Page, api: MediawikiApi, other_links: list):
        try:
            local_wikidata_id = api.get_wikidata_id(page)
            found_wikidata_ids = set()
            found_wikidata_ids.add(str(local_wikidata_id))

            for other_link in other_links:
                other_site = get_mediawiki_api(
                    other_link.group(1), api.get_site().family
                )
                if not other_site:
                    continue
                other_page = other_site.get_page(other_link.group(2))
                if not other_page or not other_page.exists():
                    continue

                other_wikidata_id = other_site.get_wikidata_id(other_page)
                found_wikidata_ids.add(str(other_wikidata_id))

            if len(found_wikidata_ids) != 1:
                LOGGER.info(
                    "Found %s different Wikidata Qs: %s",
                    len(found_wikidata_ids),
                    ", ".join(found_wikidata_ids),
                )
                return False
            return True
        except:
            LOGGER.info(
                "Got an error while comparing Wikidata Qs, check if page is connected to wikidata"
            )  # ignore; will return false

        return False

    def process_page(self, page_name: str, api: MediawikiApi, replica: ReplicaDatabase):
        page = api.get_page(page_name)
        text = page.text
        entries = list(ENTRY_REGEX.finditer(text))
        requests = {}

        for entry in entries:
            entry_text = entry.group(1)
            first_link = LOCAL_LINK_REGEX.match(entry_text)

            entry_text_lower = entry_text.lower()
            if first_link and not any(
                term.lower() in entry_text_lower
                for term in self.get_task_configuration("keep_terms")
            ):
                request_text = first_link.group(1).replace(" ", "_")
                if len(request_text) > 0:
                    request_text = request_text[0].capitalize() + request_text[1:]
                    requests[request_text] = entry.group(0)

        page_titles = requests.keys()
        format_strings = ",".join(["%s"] * len(page_titles))
        existing_pages = replica.get_all(
            EXISTING_PAGE_QUERY.format(format_strings), tuple(page_titles)
        )

        removed_entries = []
        new_text = text

        LOGGER.info("-- Found %s filled requests", (str(len(existing_pages))))
        for existing_page in existing_pages:
            existing_page = existing_page["page_title"].decode("utf-8")
            existing_page_entry = requests[existing_page]
            entry_formatted = existing_page_entry.replace("\n", "")
            LOGGER.info("- Request %s (%s)", existing_page, entry_formatted)

            other_links = list(OTHER_WIKI_LINK_REGEX.finditer(existing_page_entry))

            if len(other_links) >= 1:
                LOGGER.info(
                    "Found at least 1 link to other wiki, comparing Wikidata Q's..."
                )
                local_page = api.get_page(existing_page)
                if not self.compare_wikidata_qs(local_page, api, other_links):
                    continue

            if not self.is_manual_run or manual_run.confirm_with_enter():
                new_text = new_text.replace(existing_page_entry, "")
                removed_entries.append(existing_page)

        if len(removed_entries) > 0:
            removed_length = len(removed_entries)
            if text == new_text:
                raise RuntimeError(
                    "text == new_text but at least one entry should be removed"
                )
            summary = "Botti poisti " + (
                (str(removed_length) + " täytettyä artikkelitoivetta")
                if removed_length > 3
                else (
                    "seuraavat täytetyt artikkelitoiveet: [["
                    + "]], [[".join(removed_entries)
                    + "]]"
                )
            )

            LOGGER.info(
                "Removing %s requests from page %s",
                (str(removed_length), page.title(as_link=True)),
            )
            if not self.is_manual_run or manual_run.confirm_edit():
                page.text = new_text
                page.save(summary, botflag=self.should_use_bot_flag())

    def run(self):
        api = self.get_mediawiki_api()

        replicadb = ReplicaDatabase(api.get_site().dbName())
        replicadb.request()

        if self.get_task_configuration("run") is not True:
            LOGGER.error("Disabled in configuration")
            return

        for page in self.get_task_configuration("pages"):
            LOGGER.info("")
            LOGGER.info("--- Processing page %s", page)
            self.process_page(page, api, replicadb)

        replicadb.close()


task_registry.add_task(
    FiwikiRequestedArticlesTask("2", "Requested articles clerk", "fi", "wikipedia")
)
