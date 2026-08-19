import { Component, type ErrorInfo, type ReactNode } from "react";
export class FeatureBoundary extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) {}
  componentDidUpdate(previous: Readonly<{ children: ReactNode; resetKey: string }>) { if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false }); }
  render() { return this.state.failed ? <section className="feature-panel"><div className="empty-state"><strong>This surface could not be shown</strong><span>The rest of the vault is still available. Your vault was not changed.</span></div></section> : this.props.children; }
}
