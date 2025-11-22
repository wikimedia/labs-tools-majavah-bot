from majavahbot.tasks.task_3_bot_status import Block


def test_Block_parse_format() -> None:
    block = Block.parse(
        {
            "blockid": 25197918,
            "blockedby": "Theleekycauldron",
            "blockedbyid": 32403560,
            "blockreason": "WugBot task 2 being replaced, [[Special:Diff/1298191373|permission given by operator]] to effect handoff via pblock",
            "blockedtimestamp": "2025-07-12T20:18:29Z",
            "blockexpiry": "infinite",
            "blockpartial": "",
            "blockedtimestampformatted": "23:18, 12 July 2025",
        }
    )

    assert (
        block.format()
        == "Partially blocked by {{no ping|Theleekycauldron}} on 12 Jul 2025.<br/>Block reason is 'WugBot task 2 being replaced, [[Special:Diff/1298191373|permission given by operator]] to effect handoff via pblock{{'}}"
    )
