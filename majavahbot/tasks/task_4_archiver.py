import pywikibot

from majavahbot.api import ReplicaDatabase
from majavahbot.api.manual_run import confirm_edit
from majavahbot.tasks import Task, task_registry

QUERY = '''
select
    page_id,
    page_namespace,
    page_title,
    page_len
from page
where
    page_namespace in ({namespaces})
    and page_title not like '%/%'
    and page_len > 5000
    and not exists (
        select 1
        from templatelinks
        where tl_from = page_id
        and (tl_title = "MajavahBot/config" or tl_title = "MajavahBot/no-autotag")
        and tl_namespace = 2
    )
    and not exists (
        select 1
        from page_restrictions
        where pr_page = page_id
        and pr_type = 'edit'
        and pr_level = 'sysop'
    )
order by page_len desc
limit 20;
'''


class AchieverBot(Task):
    def __init__(self, number, name, site, family):
        super().__init__(number, name, site, family)
        self.supports_manual_run = True
        self.register_task_configuration('User:MajavahBot/Options')

    def run(self):
        if self.param != 'autosetup':
            print('Unknown mode')
            return

        self.merge_task_configuration(
            autosetup_run=False,
            autosetup_tag='{{subst:Përdoruesi:MajavahBot/arkivimi automatik}}',
            autosetup_summary='MajavahBot: Vendosja e faqes së diskutimit për arkivim automatik',
            autosetup_namespaces=[1],
        )

        if self.get_task_configuration('autosetup_run') is not True:
            print('Disabled in configuration')
            return

        api = self.get_mediawiki_api()
        replicadb = ReplicaDatabase(api.get_site().dbName())

        replag = replicadb.get_replag()
        if replag > 10:
            print('Replag is over 10 seconds, not processing! (' + str(replag) + ')')
            return

        namespaces = self.get_task_configuration('autosetup_namespaces')
        namespace_placeholders = ','.join(['%s'] * len(namespaces))

        results = replicadb.get_all(
            QUERY.format(namespaces=namespace_placeholders), tuple(namespaces)
        )

        print('-- Got %s pages' % (str(len(results))))
        for page_from_db in results:
            page_id = page_from_db[0]
            page_ns = page_from_db[1]
            page_name = page_from_db[2].decode('utf-8')

            page = pywikibot.Page(api.get_site(), page_name, ns=page_ns)
            page_text = page.get()
            assert page.pageid == page_id

            print('Tagging page ', page.title())
            new_text = self.get_task_configuration('autosetup_tag') + '\n\n' + page_text
            if (
                new_text != page_text
                and self.should_edit()
                and (not self.is_manual_run or confirm_edit())
            ):
                api.site.login()
                page.text = new_text
                page.save(
                    self.get_task_configuration('autosetup_summary'),
                    watch=False,
                    minor=False,
                    botflag=self.should_use_bot_flag(),
                )
                self.record_trial_edit()


task_registry.add_task(AchieverBot(4, 'Archive utility', 'sq', 'wikipedia'))
