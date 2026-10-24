import { useEffect, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
export interface MenuAction {
  id: string;
  label: string;
  description?: string;
  category?: string;
  disabled?: boolean;
}
export interface MenuState {
  x: number;
  y: number;
  kind: "canvas" | "card" | "edge" | "area";
  id?: string;
  point?: { x: number; y: number };
}
export function ContextMenu({
  menu,
  items,
  onChoose,
  onClose,
}: {
  menu: MenuState;
  items: MenuAction[];
  onChoose: (id: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const place = () => {
      const margin = 12;
      element.style.maxHeight =
        Math.max(0, Math.min(560, innerHeight - margin * 2)) + "px";
      element.style.maxWidth = Math.max(0, innerWidth - margin * 2) + "px";
      const bounds = element.getBoundingClientRect();
      element.style.left =
        Math.max(margin, Math.min(menu.x, innerWidth - bounds.width - margin)) +
        "px";
      element.style.top =
        Math.max(
          margin,
          Math.min(menu.y, innerHeight - bounds.height - margin),
        ) + "px";
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(element);
    window.addEventListener("resize", place);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
    };
  }, [menu.x, menu.y]);
  useEffect(() => {
    const previous = document.activeElement;
    (
      ref.current?.querySelector<HTMLElement>(
        "[role=menuitem]:not(:disabled)",
      ) ?? ref.current
    )?.focus({ preventScroll: true });
    const close = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", close, true);
    return () => {
      document.removeEventListener("pointerdown", close, true);
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);
  let category = "";
  return createPortal(
    <div
      className="context-menu"
      ref={ref}
      role="menu"
      tabIndex={-1}
      aria-label={menu.kind === "canvas" ? "Add a card" : "Actions"}
      style={{
        left: 12,
        top: 12,
        maxHeight: Math.max(0, Math.min(560, innerHeight - 24)),
        maxWidth: Math.max(0, innerWidth - 24),
      }}
      onKeyDown={(e) => {
        const buttons = [
            ...ref.current!.querySelectorAll<HTMLElement>(
              "[role=menuitem]:not(:disabled)",
            ),
          ],
          i = buttons.indexOf(document.activeElement as HTMLElement);
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
          e.preventDefault();
          buttons[
            e.key === "Home"
              ? 0
              : e.key === "End"
                ? buttons.length - 1
                : (i + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) %
                  buttons.length
          ]?.focus();
        }
      }}
    >
      {items.map((item) => {
        const heading =
          item.category && category !== item.category ? item.category : null;
        category = item.category ?? category;
        return (
          <div key={item.id}>
            {heading && <h3>{heading}</h3>}
            <button
              role="menuitem"
              disabled={item.disabled}
              onClick={() => onChoose(item.id)}
            >
              <strong>{item.label}</strong>
              {item.description && <small>{item.description}</small>}
            </button>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
