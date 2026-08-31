import hashlib
import logging
from collections import deque
from dataclasses import dataclass, replace
from typing import Any
from xml.etree import ElementTree

from mobile_tools.base import MobileElementInfo, is_in_place_control
from mobile_tools.keyboard_scanner import MobileKeyboardScannerTool
from mobile_tools.tree import bounds_center, bounds_size, get_interactive_elements, parse_mobile_tree
from mobile_tools.utils.session import MOBILE_SESSION, get_mobile_run_logs_dir
from tools.base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)

_HORIZONTAL_CONTAINER_CLASSES = ("horizontalscrollview", "viewpager", "viewpager2", "tablayout")
_DRAWER_LABELS = ("open drawer", "navigate up", "open navigation", "menu", "hamburger")


@dataclass(frozen=True)
class MobileScanSnapshot:
    """Represents a snapshot of the mobile screen at a specific point in time, including the current activity, accessibility tree, screenshot, and parsed elements."""

    activity: str
    tree_xml: str
    screenshot: str
    elements: list[MobileElementInfo]


class MobileScreenScannerTool(Tool):
    """Navigate mobile screens and collect scan snapshots."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.max_steps = int(self.config.get("max_steps", 50))
        self.max_activities = int(self.config.get("max_activities", 3))
        self.max_depth = int(self.config.get("max_depth", 5))
        self.target_app_package = self.config.get("target_app_package")
        self._snapshots: list[MobileScanSnapshot] = []
        self._seen_activities: set[str] = set()
        self._seen_screens: set[str] = set()
        self._screen_activities: dict[str, str] = {}
        self._visited_activities: list[str] = []
        self._activity_screenshots: dict[str, str] = {}
        self._keyboard_results: list[dict[str, Any]] = []
        self._path: list[str] = []
        self._page_screenshot: str | None = None
        self._step = 0
        self._step_limit = self.max_steps
        self._snapshot_index = 0

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            await self.scan_screen(
                max_steps=int(kwargs.get("max_steps", self.max_steps)),
                max_activities=int(kwargs.get("max_activities", self.max_activities)),
                max_depth=int(kwargs.get("max_depth", self.max_depth)),
                target_app_package=kwargs.get("target_app_package", self.target_app_package),
            )
            data = self.result()
            return ToolResult(
                tool_name="mobile-screen-scanner",
                status=ToolStatus.SUCCESS,
                data=data,
                metadata={"activity_count": len(data["visited_activities"])},
            )
        except Exception as exc:
            logger.exception("Mobile screen scanner failed")
            return ToolResult("mobile-screen-scanner", ToolStatus.FAILURE, {}, error=str(exc))

    async def scan_screen(
        self,
        *,
        max_steps: int | None = None,
        max_activities: int | None = None,
        max_depth: int | None = None,
        target_app_package: str | None = None,
    ) -> None:
        step_limit = self.max_steps if max_steps is None else max_steps
        self._step_limit = step_limit
        activity_limit = self.max_activities if max_activities is None else max_activities
        depth_limit = self.max_depth if max_depth is None else max_depth
        queue: deque[tuple[str, str, int]] = deque()

        await self._ensure_scope(target_app_package)
        snapshot = await self._snapshot()
        self._page_screenshot = self._page_screenshot or snapshot.screenshot
        root_hash = self._screen_hash(snapshot.tree_xml)
        self._screen_activities[root_hash] = self._activity_name(snapshot)
        screen_edges: dict[str, tuple[str, str, str] | None] = {root_hash: None}
        drawer_stop = False
        drawer_result = await self._try_open_drawer(snapshot, target_app_package) if depth_limit > 0 else None
        if drawer_result is not None:
            # If a drawer was opened, perform a vertical scan on the drawer screen and then return to the root screen
            drawer_snapshot, action, bounds = drawer_result
            drawer_hash = self._screen_hash(drawer_snapshot.tree_xml)
            screen_edges.setdefault(drawer_hash, (root_hash, action, bounds))
            drawer_stop, _ = await self._scan_vertical(
                drawer_snapshot,
                depth=0,
                queue=queue,
                screen_edges=screen_edges,
                step_limit=step_limit,
                activity_limit=activity_limit,
                depth_limit=depth_limit,
                target_app_package=target_app_package,
                reserved_actions=1,
                stop_at_activity_limit=False,
            )
            await self._back()
            await self._ensure_scope(target_app_package)
            snapshot = await self._snapshot()
            if self._screen_hash(snapshot.tree_xml) != root_hash:
                logger.warning("Mobile scan could not restore the root screen after closing the drawer")

        stop, current_hash = await self._scan_vertical(
            snapshot,
            depth=0,
            queue=queue,
            screen_edges=screen_edges,
            step_limit=step_limit,
            activity_limit=activity_limit,
            depth_limit=depth_limit,
            target_app_package=target_app_package,
        )
        stop = stop or drawer_stop

        while queue and not stop and self._step + 2 <= step_limit:
            bounds, parent_hash, depth = queue.popleft()
            restored, current_hash = await self._restore_screen(
                current_hash,
                parent_hash,
                screen_edges,
                step_limit=step_limit,
                reserved_actions=2,
                target_app_package=target_app_package,
            )
            if not restored:
                logger.warning("Mobile scan could not restore parent screen before tapping %s", bounds)
                continue

            await self._tap(bounds)
            await self._ensure_scope(target_app_package)
            snapshot = await self._snapshot()
            reached_hash = self._screen_hash(snapshot.tree_xml)
            parent_activity = self._screen_activities.get(parent_hash)
            reached_activity = self._activity_name(snapshot)
            if (
                reached_hash != parent_hash
                and parent_activity is not None
                and reached_activity == parent_activity
            ):
                current_hash = await self._handle_dialog(snapshot, parent_hash, target_app_package)
                continue

            if reached_hash != parent_hash:
                screen_edges.setdefault(reached_hash, (parent_hash, "tap", bounds))

            if reached_hash not in self._seen_screens:
                # If the new screen has not been seen before, perform a vertical scan on it
                stop, current_hash = await self._scan_vertical(
                    snapshot,
                    depth=depth,
                    queue=queue,
                    screen_edges=screen_edges,
                    step_limit=step_limit,
                    activity_limit=activity_limit,
                    depth_limit=depth_limit,
                    target_app_package=target_app_package,
                    reserved_actions=1,
                )
            else:
                current_hash = reached_hash
                stop = not self._record_activity(snapshot, activity_limit)
                stop = stop or len(self._visited_activities) >= activity_limit

            if reached_hash == parent_hash:
                continue

            await self._back()  # Return to the previous screen after tapping an element
            await self._ensure_scope(target_app_package)
            current_hash = self._screen_hash((await self._snapshot()).tree_xml)
            if current_hash != parent_hash and self._step < step_limit:
                await self._back()
                await self._ensure_scope(target_app_package)
                current_hash = self._screen_hash((await self._snapshot()).tree_xml)
            if current_hash != parent_hash:
                logger.warning("Mobile scan could not return to parent screen after tapping %s", bounds)

    async def _handle_dialog(
        self,
        snapshot: MobileScanSnapshot,
        parent_hash: str,
        target_app_package: str | None,
    ) -> str:
        dialog_hash = self._screen_hash(snapshot.tree_xml)
        self._screen_activities.setdefault(dialog_hash, self._activity_name(snapshot))
        if dialog_hash not in self._seen_screens:
            self._seen_screens.add(dialog_hash)
            self._snapshots.append(snapshot)

        await self._back()
        await self._ensure_scope(target_app_package)
        dismissed_snapshot = await self._snapshot()
        dismissed_hash = self._screen_hash(dismissed_snapshot.tree_xml)
        self._screen_activities.setdefault(dismissed_hash, self._activity_name(dismissed_snapshot))
        if dismissed_hash == dialog_hash:
            logger.warning("Mobile dialog remained open after back")
            return dismissed_hash
        return parent_hash

    async def _try_open_drawer(
        self,
        snapshot: MobileScanSnapshot,
        target_app_package: str | None,
    ) -> tuple[MobileScanSnapshot, str, str] | None:
        """Attempt to open a navigation drawer if present on the current screen.
        Returns a tuple of (drawer_snapshot, action, bounds) if a drawer was opened,
        or None if no drawer was found or the drawer could not be opened."""
        if self._step + 2 > self._step_limit:
            return None

        baseline_hash = self._screen_hash(snapshot.tree_xml)
        candidate = next(
            (
                element
                for element in snapshot.elements
                if element.clickable
                and element.bounds
                and any(label in (element.content_desc or "").casefold() for label in _DRAWER_LABELS)
            ),
            None,
        )
        size: dict[str, int] | None = None
        if candidate is None:
            size = await MOBILE_SESSION.get_window_size()
            for element in snapshot.elements:
                if (
                    not element.clickable
                    or not element.bounds
                    or "imagebutton" not in (element.class_name or "").casefold()
                ):
                    continue
                try:
                    x, y = bounds_center(element.bounds)
                except ValueError:
                    continue
                if x < size["width"] * 0.15 and y < size["height"] * 0.12:
                    candidate = element
                    break

        if candidate is not None:
            await self._tap(candidate.bounds or "")
            action, bounds = "tap", candidate.bounds or ""
        else:
            await self._drawer_swipe(size)
            action, bounds = "drawer_swipe", ""

        await self._ensure_scope(target_app_package)
        drawer_snapshot = await self._snapshot()
        if self._screen_hash(drawer_snapshot.tree_xml) == baseline_hash:
            return None
        return drawer_snapshot, action, bounds

    async def _scan_vertical(
        self,
        snapshot: MobileScanSnapshot,
        *,
        depth: int,
        queue: deque[tuple[str, str, int]],
        screen_edges: dict[str, tuple[str, str, str] | None],
        step_limit: int,
        activity_limit: int,
        depth_limit: int,
        target_app_package: str | None,
        reserved_actions: int = 0,
        stop_at_activity_limit: bool = True,
    ) -> tuple[bool, str]:
        previous_hash: str | None = None
        consumed_element_keys: set[tuple[str, str, str, str]] = set()
        navigation_targets: list[tuple[str, str, int]] = []
        horizontal_containers: dict[tuple[str, str], str] = {}

        while True:
            tree_hash = self._screen_hash(snapshot.tree_xml)
            for container_key in self._horizontal_container_keys(snapshot.tree_xml):
                horizontal_containers.setdefault(container_key, tree_hash)
            if not self._record_activity(snapshot, activity_limit):
                return True, tree_hash

            self._process_snapshot(
                snapshot,
                depth=depth,
                depth_limit=depth_limit,
                consumed_element_keys=consumed_element_keys,
                navigation_targets=navigation_targets,
            )

            if stop_at_activity_limit and len(self._visited_activities) >= activity_limit:
                logger.debug("Stopping mobile scan after reaching %d activities", activity_limit)
                return True, tree_hash

            if previous_hash == tree_hash:
                logger.debug("Stopping mobile scan: accessibility tree unchanged after scroll")
                break
            previous_hash = tree_hash

            if self._step + reserved_actions >= step_limit:
                break
            parent_hash = tree_hash
            await self._scroll_down()
            await self._ensure_scope(target_app_package)
            snapshot = await self._snapshot()
            tree_hash = self._screen_hash(snapshot.tree_xml)
            if tree_hash != parent_hash:
                screen_edges.setdefault(tree_hash, (parent_hash, "scroll_down", ""))

        # Scan horizontal containers after vertical scanning is complete
        stop, tree_hash = await self._scan_horizontal(
            horizontal_containers,
            current_hash=tree_hash,
            depth=depth,
            depth_limit=depth_limit,
            consumed_element_keys=consumed_element_keys,
            navigation_targets=navigation_targets,
            screen_edges=screen_edges,
            step_limit=step_limit,
            activity_limit=activity_limit,
            target_app_package=target_app_package,
            reserved_actions=reserved_actions,
            stop_at_activity_limit=stop_at_activity_limit,
        )
        await self._run_keyboard_scan(
            target_app_package,
            max_steps=step_limit - self._step - reserved_actions,
        )
        queue.extend(navigation_targets)
        return stop, tree_hash

    async def _run_keyboard_scan(
        self,
        target_app_package: str | None,
        *,
        max_steps: int,
    ) -> None:
        if max_steps <= 0:
            return
        result = await MobileKeyboardScannerTool(
            {
                "step_budget": max_steps,
                "target_app_package": target_app_package,
            }
        ).execute()
        self._keyboard_results.append(result.data)
        keyboard_steps = int(result.data.get("total_steps", 0))
        self._path.extend(["dpad_down"] * keyboard_steps)
        self._step += keyboard_steps

    async def _scan_horizontal(
        self,
        containers: dict[tuple[str, str], str],
        *,
        current_hash: str,
        depth: int,
        depth_limit: int,
        consumed_element_keys: set[tuple[str, str, str, str]],
        navigation_targets: list[tuple[str, str, int]],
        screen_edges: dict[str, tuple[str, str, str] | None],
        step_limit: int,
        activity_limit: int,
        target_app_package: str | None,
        reserved_actions: int,
        stop_at_activity_limit: bool,
    ) -> tuple[bool, str]:
        for baseline_hash in containers.values():
            restored, current_hash = await self._restore_screen(
                current_hash,
                baseline_hash,
                screen_edges,
                step_limit=step_limit,
                reserved_actions=reserved_actions + 2,
                target_app_package=target_app_package,
            )
            if not restored:
                logger.warning("Mobile scan could not restore a horizontal container baseline")
                continue

            changed_swipes = 0
            stop = False
            while self._step + reserved_actions + changed_swipes + 2 <= step_limit:
                previous_hash = current_hash
                await self._swipe_left()
                await self._ensure_scope(target_app_package)
                snapshot = await self._snapshot()
                current_hash = self._screen_hash(snapshot.tree_xml)
                if current_hash == previous_hash:
                    logger.debug("Stopping horizontal scan: accessibility tree unchanged after swipe")
                    break

                changed_swipes += 1
                screen_edges.setdefault(current_hash, (previous_hash, "swipe_left", ""))
                if not self._record_activity(snapshot, activity_limit):
                    stop = True
                    break
                self._process_snapshot(
                    snapshot,
                    depth=depth,
                    depth_limit=depth_limit,
                    consumed_element_keys=consumed_element_keys,
                    navigation_targets=navigation_targets,
                )
                if stop_at_activity_limit and len(self._visited_activities) >= activity_limit:
                    stop = True
                    break

            for _ in range(changed_swipes):
                await self._swipe_right()
                await self._ensure_scope(target_app_package)
                current_hash = self._screen_hash((await self._snapshot()).tree_xml)
                if current_hash == baseline_hash:
                    break
            if current_hash != baseline_hash:
                logger.warning("Mobile scan could not restore a horizontal container baseline")
            if stop:
                return True, current_hash

        return False, current_hash

    def _process_snapshot(
        self,
        snapshot: MobileScanSnapshot,
        *,
        depth: int,
        depth_limit: int,
        consumed_element_keys: set[tuple[str, str, str, str]],
        navigation_targets: list[tuple[str, str, int]],
    ) -> None:
        tree_hash = self._screen_hash(snapshot.tree_xml)
        self._screen_activities.setdefault(tree_hash, self._activity_name(snapshot))
        if tree_hash in self._seen_screens:
            return
        self._seen_screens.add(tree_hash)

        new_elements = []
        for element in snapshot.elements:
            key = self._element_key(element)
            if key not in consumed_element_keys:
                consumed_element_keys.add(key)
                new_elements.append(element)
        if new_elements:
            unique_snapshot = (
                snapshot
                if len(new_elements) == len(snapshot.elements)
                else replace(snapshot, elements=new_elements)
            )
            self._snapshots.append(unique_snapshot)

        if depth >= depth_limit:
            return
        for element in get_interactive_elements(new_elements):
            if element.clickable and not is_in_place_control(element):
                navigation_targets.append((element.bounds or "", tree_hash, depth + 1))

    async def _restore_screen(
        self,
        current_hash: str,
        target_hash: str,
        screen_edges: dict[str, tuple[str, str, str] | None],
        *,
        step_limit: int,
        reserved_actions: int,
        target_app_package: str | None,
    ) -> tuple[bool, str]:
        """Restore the current screen to the target screen.
        Returns a tuple of (restored, current_hash) where restored is True if the screen was successfully restored,
        and current_hash is the hash of the current screen after restoration."""
        if current_hash == target_hash:
            return True, current_hash

        current_ancestors: set[str] = set()
        cursor = current_hash
        while cursor in screen_edges:
            current_ancestors.add(cursor)
            edge = screen_edges[cursor]
            if edge is None:
                break
            cursor = edge[0]

        forward_edges: list[tuple[str, tuple[str, str, str]]] = []
        cursor = target_hash
        while cursor not in current_ancestors:
            edge = screen_edges.get(cursor)
            if edge is None:
                return False, current_hash
            forward_edges.append((cursor, edge))
            cursor = edge[0]
        common_hash = cursor

        while current_hash != common_hash:
            if self._step + reserved_actions >= step_limit:
                return False, current_hash
            edge = screen_edges.get(current_hash)
            if edge is None:
                return False, current_hash
            expected_hash, action, _ = edge
            # Reverse the action to return to the previous screen
            if action in {"tap", "drawer_swipe"}:
                await self._back()
            elif action == "scroll_down":
                await self._scroll_up()
            else:
                await self._swipe_right()
            await self._ensure_scope(target_app_package)
            current_hash = self._screen_hash((await self._snapshot()).tree_xml)
            if current_hash != expected_hash:
                return False, current_hash

        for expected_hash, (_, action, bounds) in reversed(forward_edges):
            if self._step + reserved_actions >= step_limit:
                return False, current_hash
            # Reverse the action to return to the previous screen
            if action == "tap":
                await self._tap(bounds)
            elif action == "drawer_swipe":
                await self._drawer_swipe()
            elif action == "scroll_down":
                await self._scroll_down()
            else:
                await self._swipe_left()
            await self._ensure_scope(target_app_package)
            current_hash = self._screen_hash((await self._snapshot()).tree_xml)
            if current_hash != expected_hash:
                return False, current_hash

        return True, current_hash

    def is_screen_known(self, tree_xml: str) -> bool:
        """Return whether an accessibility tree has already been scanned."""
        return self._screen_hash(tree_xml) in self._seen_screens

    def _record_activity(self, snapshot: MobileScanSnapshot, activity_limit: int) -> bool:
        activity = self._activity_name(snapshot)
        if activity in self._seen_activities:
            return True
        if len(self._visited_activities) >= activity_limit:
            logger.debug("Stopping mobile scan before exceeding %d activities", activity_limit)
            return False
        self._seen_activities.add(activity)
        self._visited_activities.append(activity)
        self._activity_screenshots[activity] = snapshot.screenshot
        return True

    @staticmethod
    def _activity_name(snapshot: MobileScanSnapshot) -> str:
        return snapshot.activity.strip() or "unknown"

    @staticmethod
    def _element_key(element: MobileElementInfo) -> tuple[str, str, str, str]:
        return (
            element.resource_id or "",
            element.content_desc or "",
            element.text or "",
            element.bounds or "",
        )

    @staticmethod
    def _horizontal_container_keys(tree_xml: str) -> set[tuple[str, str]]:
        try:
            root = ElementTree.fromstring(tree_xml)
        except ElementTree.ParseError:
            return set()

        containers = set()
        for node in root.iter():
            if (node.attrib.get("scrollable") or "").strip().casefold() not in {"true", "1"}:
                continue
            class_name = MobileScreenScannerTool._node_attr(node, "class", "className", "type").casefold()
            resource_id = MobileScreenScannerTool._node_attr(node, "resource-id", "resourceId")
            bounds = MobileScreenScannerTool._node_attr(node, "bounds")
            known_class = any(name in class_name for name in _HORIZONTAL_CONTAINER_CLASSES)
            try:
                width, height = bounds_size(bounds)
                wide_bounds = width > height
            except ValueError:
                wide_bounds = False
            if known_class or wide_bounds:
                containers.add((resource_id, bounds))
        return containers

    @staticmethod
    def _node_attr(node: ElementTree.Element, *names: str) -> str:
        for name in names:
            value = (node.attrib.get(name) or "").strip()
            if value:
                return value
        return ""

    def result(self) -> dict[str, Any]:
        return {
            "page_screenshot": self._page_screenshot,
            "activity_screenshots": self._activity_screenshots,
            "visited_activities": self._visited_activities,
            "path": self._path,
            "steps": self._step,
            "keyboard_results": self._keyboard_results,
            "snapshots": self._snapshots,
        }

    async def _ensure_scope(self, target_app_package: str | None) -> None:
        if target_app_package and await MOBILE_SESSION.get_current_package() != target_app_package:
            raise RuntimeError(f"Mobile scan left target package {target_app_package}.")

    async def _snapshot(self) -> MobileScanSnapshot:
        self._snapshot_index += 1
        tree = await MOBILE_SESSION.get_accessibility_tree()
        screenshot = await MOBILE_SESSION.take_screenshot()
        activity = await MOBILE_SESSION.get_current_activity()
        self._save_tree_snapshot(tree)
        return MobileScanSnapshot(
            activity=activity,
            tree_xml=tree,
            screenshot=screenshot,
            elements=parse_mobile_tree(tree, page_screenshot=screenshot),
        )

    def _save_tree_snapshot(self, tree: str) -> None:
        path = get_mobile_run_logs_dir() / f"mobile_tree_{self._snapshot_index:04d}.xml"
        path.write_text(self._format_tree_snapshot(tree), encoding="utf-8")

    async def _scroll_down(self) -> None:
        await MOBILE_SESSION.scroll_down()
        self._path.append("scroll_down")
        self._step += 1

    async def _scroll_up(self) -> None:
        await MOBILE_SESSION.scroll_up()
        self._path.append("scroll_up")
        self._step += 1

    async def _swipe_left(self) -> None:
        await MOBILE_SESSION.swipe_left()
        self._path.append("swipe_left")
        self._step += 1

    async def _swipe_right(self) -> None:
        await MOBILE_SESSION.swipe_right()
        self._path.append("swipe_right")
        self._step += 1

    async def _drawer_swipe(self, size: dict[str, int] | None = None) -> None:
        size = size or await MOBILE_SESSION.get_window_size()
        y = size["height"] // 2
        await MOBILE_SESSION.swipe(0, y, int(size["width"] * 0.7), y, 300)
        self._path.append("swipe_open_drawer")
        self._step += 1

    async def _tap(self, bounds: str) -> None:
        await MOBILE_SESSION.tap_bounds(bounds)
        self._path.append(f"tap:{bounds}")
        self._step += 1

    async def _back(self) -> None:
        await MOBILE_SESSION.back()
        self._path.append("back")
        self._step += 1

    @staticmethod
    def _screen_hash(tree_xml: str) -> str:
        return hashlib.md5(tree_xml.encode()).hexdigest()

    def _format_tree_snapshot(self, tree: str) -> str:
        try:
            root = ElementTree.fromstring(tree)
        except ElementTree.ParseError:
            return f"{tree}\n"
        ElementTree.indent(root, space="  ")
        return f"{ElementTree.tostring(root, encoding='unicode')}\n"
