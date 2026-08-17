import { fireEvent, render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("minimal shell", () => {
  it("opens on the financial picture", () => {
    const { getByRole, getByText } = render(<App />);
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(getByText("$48,240.18")).toBeInTheDocument();
    expect(getByText("Corroborated · July 31, 2026")).toBeInTheDocument();
    expect(getByText("Synthetic local corpus")).toBeInTheDocument();
    expect(getByText("Fixture boundary")).toBeInTheDocument();
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(getByText("Capture before reading")).toBeInTheDocument();
    expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).toBeInTheDocument();
  });

  it("acknowledges document capture as local-only", async () => {
    const user = userEvent.setup();
    const { getByRole } = render(<App />);
    await user.click(getByRole("button", { name: /add document/i }));
    expect(getByRole("status")).toHaveTextContent("Nothing has left this device.");
  });

  it("shows the demo vault boundary and can reset it", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);

    expect(getByText("Synthetic local corpus")).toBeInTheDocument();
    expect(getByText("Offline demo vault seeded from checked-in fixtures.")).toBeInTheDocument();

    await user.click(getByRole("button", { name: /reset demo vault/i }));
    expect(getByRole("status")).toHaveTextContent("Demo vault reset to the checked-in fixture snapshot.");
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
  });

  it("keeps review count visible as a pending state", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "ReviewWhat needs you2" }));
    expect(getByRole("heading", { name: "2 questions are waiting" })).toBeInTheDocument();
    expect(getByText(/A proposal will always wait for an explicit yes/)).toBeInTheDocument();
  });

  it("shows the selected document detail inside documents", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    await user.click(getByRole("button", { name: /fidelity-brokerage-2026-05-to-2026-07\.pdf/i }));
    expect(getByText("Generated locally")).toBeInTheDocument();
    expect(getByText("2 pages")).toBeInTheDocument();
    expect(getByText("Queued for reading")).toBeInTheDocument();
    expect(getByText("Synthetic PDF · brokerage statement · pages 1–2")).toBeInTheDocument();
  });

  it("navigates from a document to related evidence without losing provenance", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    await user.click(getByRole("button", { name: /fidelity-brokerage-2026-05-to-2026-07\.pdf/i }));
    await user.click(getByRole("button", { name: /north river savings statement/i }));
    expect(getByRole("heading", { name: "north-river-savings-2026-05-to-2026-07.pdf" })).toBeInTheDocument();
    expect(getByText("Synthetic PDF · savings statement · page 1")).toBeInTheDocument();
    expect(getByRole("button", { name: /Taxable Brokerage statementcorroborates.*pages 1–2/i })).toBeInTheDocument();
  });

  it("shows the selected queue item inside review", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "ReviewWhat needs you2" }));
    await user.click(getByRole("button", { name: /merchant category/i }));
    expect(getByText("Merchant")).toBeInTheDocument();
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();
    expect(getByText("proposal")).toBeInTheDocument();
  });

  it("keeps the selected document when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole } = render(<App />);

    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    await user.click(getByRole("button", { name: /fidelity-brokerage-2026-05-to-2026-07\.pdf/i }));
    expect(getByRole("heading", { name: "fidelity-brokerage-2026-05-to-2026-07.pdf" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    expect(getByRole("heading", { name: "fidelity-brokerage-2026-05-to-2026-07.pdf" })).toBeInTheDocument();
    expect(getByRole("button", { name: /open page review/i })).toBeInTheDocument();
  });

  it("keeps the selected review question when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);

    await user.click(getByRole("button", { name: /review.*what needs you2/i }));
    await user.click(getByRole("button", { name: /merchant category/i }));
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    await user.click(getByRole("button", { name: /review.*what needs you2/i }));
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();
    expect(getByRole("button", { name: /open document review/i })).toBeInTheDocument();
  });

  it("lets the local capture notice be dismissed", async () => {
    const { getByRole, queryByRole } = render(<App />);

    fireEvent.click(getByRole("button", { name: /add document/i }));
    expect(getByRole("status")).toHaveTextContent("Nothing has left this device.");

    fireEvent.click(getByRole("button", { name: /dismiss notice/i }));
    expect(queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the trust surface as explicit local guarantees", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    expect(getByRole("heading", { name: "Trust" })).toBeInTheDocument();
    expect(getByText("Local by default", { selector: "strong" })).toBeInTheDocument();
    expect(getByText("No silent inference", { selector: "strong" })).toBeInTheDocument();
    expect(getByText("Anchoring status", { selector: "strong" })).toBeInTheDocument();
  });

  it("states the bridge boundary without claiming a live vault", () => {
    const { getByText } = render(<App />);
    expect(getByText(/bridge boundary ready, no live vault connected/i)).toBeInTheDocument();
  });

  it("keeps fixture preview usable when no host bridge is injected", () => {
    const { getByText, queryByPlaceholderText } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByPlaceholderText("/path/to/vault")).not.toBeInTheDocument();
  });

  it("keeps manual directory entry as the browser fallback", () => {
    const { getByText, queryByLabelText, queryByRole } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByRole("button", { name: /choose folder/i })).not.toBeInTheDocument();
    expect(queryByLabelText("Vault directory")).not.toBeInTheDocument();
  });

  it("asks the native host to choose a vault directory and copies the selection into the manual field", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const pickVaultDirectory = vi.fn(async () => "/chosen/local-vault");
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory,
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(pickVaultDirectory).toHaveBeenCalledTimes(1);
      expect(getByLabelText("Vault directory")).toHaveValue("/chosen/local-vault");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("treats a cancelled native picker as a no-op and keeps the manual path", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const pickVaultDirectory = vi.fn(async () => null);
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory,
    };

    try {
      const { getByLabelText, getByRole, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/manual/vault");

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(pickVaultDirectory).toHaveBeenCalledTimes(1);
      expect(getByLabelText("Vault directory")).toHaveValue("/manual/vault");
      expect(queryByRole("status")).toBeNull();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("keeps picker failures bounded and leaves manual entry available", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const hostFailure = "dialog failed while reading /private/vault";
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory: async () => { throw new Error(hostFailure); },
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/manual/vault");

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(getByRole("status")).toHaveTextContent(/folder picker could not be opened/i);
      expect(getByRole("status")).not.toHaveTextContent(hostFailure);
      expect(getByLabelText("Vault directory")).toHaveValue("/manual/vault");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("opens a local vault through the injected host bridge", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation }: { requestId: string; operation: string; payload: Record<string, unknown> }) => ({
        protocol: "1.0",
        request_id: "req",
        ok: true,
        result: (operation === "bridge.open_vault"
          ? { state: "opened" }
          : { surface: "overview", job_id: "job-1", data: { as_of: "August 1, 2026" } }) as T,
      }),
    };

    try {
      const { getByLabelText, getByRole, getByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByText("Local vault opened. Surface data is now coming from the bridge.")).toBeInTheDocument();
      expect(getByText("Bridge-facing surface adapter")).toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("validates the vault-open form before calling the host", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let calls = 0;
    window.orionVivaBridge = {
      request: async <T,>() => {
        calls += 1;
        return { protocol: "1.0", request_id: "req", ok: true, result: { state: "opened" } as T };
      },
    };

    try {
      const { getByRole, getByText } = render(<App />);
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByText("Enter a vault directory and passphrase to open a local vault.")).toBeInTheDocument();
      expect(calls).toBe(0);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("shows an opening state while the host request is pending", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let resolveRequest: (() => void) | undefined;
    window.orionVivaBridge = {
      request: <T,>() => new Promise<{ protocol: string; request_id: string; ok: boolean; result: T }>((resolve) => {
        resolveRequest = () => resolve({
          protocol: "1.0",
          request_id: "req",
          ok: true,
          result: {} as T,
        });
      }),
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByRole("button", { name: "Opening vault..." })).toBeDisabled();
      resolveRequest?.();
      await waitFor(() => expect(getByRole("button", { name: "Open local vault" })).toBeEnabled());
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("shows a bounded open error and clears the passphrase", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const secret = "correct horse battery staple";
    window.orionVivaBridge = {
      request: async <T,>() => ({
        protocol: "1.0",
        request_id: "req",
        ok: false,
        error: { code: "vault_open_failed", message: "internal details must not reach the UI" },
      } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string }; result?: T }),
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), secret);
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByRole("status")).toHaveTextContent("The local vault could not be opened.");
      expect(getByRole("status")).not.toHaveTextContent(secret);
      expect(getByLabelText("Passphrase")).toHaveValue("");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });
});
