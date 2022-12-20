from majavahbot.api import ReplicaDatabase
from majavahbot.tasks import Task, task_registry

QUERY = """/* MajavahBot task 7 */
select 
  concat ("{{u|", user_name, "}}") as "username", 
  (
    select 
      count(*) 
    from 
      logging 
      inner join actor on actor_id = log_actor 
    where 
      actor_user = user_id 
      and log_type = "gblblock"
  ) as "+Global block", 
  (
    select 
      count(*) 
    from 
      logging 
      inner join actor on actor_id = log_actor 
    where 
      actor_user = user_id 
      and log_type = "globalauth"
  ) as "+Global lock", 
  (
    select 
      count(*) 
    from 
      logging 
      inner join actor on actor_id = log_actor 
    where 
      actor_user = user_id 
      and log_type = "gblrename"
  ) as "+Global rename", 
  (
    select 
      count(*) 
    from 
      logging 
      inner join actor on actor_id = log_actor 
    where 
      actor_user = user_id 
      and log_type = "gblrights"
  ) as "+Global rights", 
  (
    select 
      count(*) 
    from 
      logging 
      inner join actor on actor_id = log_actor 
    where 
      actor_user = user_id 
      and log_type = "rights"
  ) as "+Rights", 
  (
    select 
      count(*) 
    from 
      logging 
      inner join actor on actor_id = log_actor 
    where 
      actor_user = user_id 
      and log_type = "abusefilter"
  ) as "+Af edits", 
  (
    (
      select 
        count(*) 
      from 
        revision 
        inner join actor on actor_id = rev_actor 
      where 
        actor_user = user_id 
      and rev_page IN (32244, 130130, 164533, 135805, 31937, 84820, 9476, 117752, 167407)
    ) + (
      select 
        count(*) 
      from 
        revision 
        inner join actor on actor_id = rev_actor 
      where 
        actor_user = user_id 
        and rev_page = 13356 
        and rev_minor_edit = 0
    )
  ) as "SR edits"
from 
  user 
  inner join user_groups on ug_user = user_id 
where 
  ug_group = "steward";
"""

PAGE_TEMPLATE = """
<div style="background: #E5E4E2; padding: 0.5em; border-radius: 0.3em;">
'''Steward statistics'''

Updated by [[User:%(user)s|]] at ~~~~~
</div><div style="background: #E5E4E2; padding: 0.5em;   -moz-border-radius: 0.3em; border-radius: 0.3em;">
{| class="wikitable sortable" style="margin-left: auto; margin-right: auto; border: none; text-align:center;"
!User!!Global block!!Global lock!!Global rename!!Global rights!!Rights (1)!!Af edits (2)!!SR edits (3)!!Total
%(results)s
|}
{{Stewards/statistics bottom}}
</div>
"""


class StewardStatsTask(Task):
    def run(self):
        api = self.get_mediawiki_api()
        site = api.get_site()

        replica = ReplicaDatabase(site.dbName())
        results = replica.get_all(QUERY)

        table = ""

        for row in results:
            (
                user,
                global_blocks,
                global_locks,
                global_renames,
                global_rights,
                rights,
                filter_edits,
                sr_edits,
            ) = row
            total = (
                global_blocks
                + global_locks
                + global_renames
                + global_rights
                + rights
                + filter_edits
                + sr_edits
            )

            table += f"|-\n| {user.decode('utf-8')} || {global_blocks} || {global_locks} || {global_renames} || {global_rights} || {rights} || {filter_edits} || {sr_edits} || {total}\n"

        content = PAGE_TEMPLATE % {"results": table, "user": site.username()}

        page = api.get_page("Stewards/statistics")
        page.text = content
        page.save("Update")


task_registry.add_task(StewardStatsTask(7, "Steward statistics", "meta", "meta"))
