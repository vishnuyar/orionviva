import { act, render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { DesktopShell } from "./BrowserShell";

afterEach(() => { window.orionVivaBridge = undefined; });

it("keeps browser return and stop confirmations visible with reachable focus", async () => {
  const user = userEvent.setup();
  let active = false;
  let notify = (_value: boolean) => {};
  const controls = {
    status: vi.fn(async () => active),
    start: vi.fn(async () => { active = true; }),
    stop: vi.fn(async () => { active = false; }),
    returnToDesktop: vi.fn(async () => { active = false; }),
    subscribe: vi.fn(async (changed: (value: boolean) => void) => { notify = changed; return () => {}; }),
  };
  const view = render(<DesktopShell controls={controls} />);
  const options = view.container.querySelector(".browser-options")!;
  expect(options).not.toHaveAttribute("open");
  await user.click(view.getByText("Browser access", { selector: "summary" }));
  await user.click(await view.findByRole("button", { name: "Open in browser" }));
  await waitFor(() => expect(view.getByRole("heading", { name: "OrionViva is open in your browser" })).toHaveFocus());
  await user.click(view.getByRole("button", { name: "Return to desktop" }));
  await waitFor(() => expect(view.getByRole("heading", { name: "Use OrionViva in your browser" })).toHaveFocus());
  expect(options).toHaveAttribute("open");
  expect(view.getByRole("heading", { name: "Your financial picture" })).toBeVisible();
  await user.click(view.getByRole("button", { name: "Open in browser" }));
  await user.click(view.getByText("Browser session active", { selector: "summary" }));
  expect(options).not.toHaveAttribute("open");
  await act(async () => { active = false; notify(false); });
  await waitFor(() => expect(view.getByRole("heading", { name: "Use OrionViva in your browser" })).toHaveFocus());
  expect(options).toHaveAttribute("open");
  await user.click(view.getByRole("button", { name: "Open in browser" }));
  await user.click(view.getByRole("button", { name: "Stop browser access" }));
  await waitFor(() => expect(view.getByRole("alert")).toHaveTextContent("Browser access has ended."));
  expect(view.getByRole("alert")).toBeVisible();
  expect(options).toHaveAttribute("open");
  await act(async () => view.unmount());
});
