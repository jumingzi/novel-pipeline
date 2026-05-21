import asyncio
from pipeline.orchestrator import ProgressBus, PipelineState


def test_progress_bus_subscribe_and_emit():
    bus = ProgressBus()
    events = []

    async def collector():
        async for event in bus.subscribe():
            events.append(event)
            if len(events) >= 2:
                break

    async def emitter():
        await bus.emit({"agent_id": "agent1", "status": "running"})
        await bus.emit({"agent_id": "agent1", "status": "done"})

    async def run():
        await asyncio.gather(collector(), emitter())

    asyncio.run(run())
    assert len(events) == 2
    assert events[0]["agent_id"] == "agent1"


def test_pipeline_state_initial():
    state = PipelineState()
    assert state.current_step == "idle"
    assert state.progress == 0.0


def test_pipeline_state_advance():
    state = PipelineState()
    state.advance("agent1", "running")
    assert state.current_step == "agent1"
    state.advance("agent1", "done")
    assert state.progress == 0.25


def test_pipeline_state_error():
    state = PipelineState()
    state.set_error("API call failed")
    assert state.error == "API call failed"
    assert state.is_error
