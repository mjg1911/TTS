from piper.windows_tray.single_instance import InstanceRole, SingleInstance


class FakeKernel:
    def __init__(self, already_exists: bool) -> None:
        self.already_exists = already_exists
        self.signals = 0
        self.released: list[int] = []
        self.closed: list[int] = []

    def create_event(self, name: str) -> int:
        return 10

    def create_mutex(self, name: str) -> tuple[int, bool]:
        return 20, self.already_exists

    def signal_event(self, handle: int) -> None:
        self.signals += 1

    def wait_event(self, handle: int) -> None:
        raise RuntimeError("not used by this test")

    def release_mutex(self, handle: int) -> None:
        self.released.append(handle)

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


def test_secondary_signals_existing_instance_and_does_not_own_mutex() -> None:
    kernel = FakeKernel(already_exists=True)
    instance = SingleInstance(kernel)

    assert instance.acquire() is InstanceRole.SECONDARY
    assert kernel.signals == 1
    instance.close()

    assert kernel.released == []
    assert kernel.closed == [10, 20]


def test_primary_owns_mutex_without_signaling_and_releases_handles_on_close() -> None:
    kernel = FakeKernel(already_exists=False)
    instance = SingleInstance(kernel)

    assert instance.acquire() is InstanceRole.PRIMARY
    assert kernel.signals == 0

    instance.close()

    assert kernel.released == [20]
    assert kernel.closed == [10, 20]
