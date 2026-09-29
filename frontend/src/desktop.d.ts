/** Narrow renderer bridge. Every method is backed by the Electron preload. */
import type { AgentBridge, CompanionBridge, DecideBridge } from '../../desktop/src/companion-types'
export type { CompanionSurface, CompanionPanel, CompanionItem, CompanionState, CompanionActionResult, CompanionMutationResult, CompanionWindowCandidate, CompanionBridge, AgentBridge, AgentStatus, AgentModel, AgentSession, AgentArtifact, AgentMessage, AgentTurnEvent, AgentSendInput, DecideBridge, DecideStatus, DecideSelection } from '../../desktop/src/companion-types'

export interface DesktopBridge {
  companion?: CompanionBridge
  /** 岛上的智能体会话；只有桌面版的浮窗才有。 */
  agent?: AgentBridge
  /** 拿主意：全局热键读到的选区；只有桌面版的浮窗才有。 */
  decide?: DecideBridge
  setTheme(theme: 'system' | 'light' | 'dark'): void
  onMenu?(cb: (name: string) => void): (() => void) | void
  onFlush?(cb: () => void): void
  flushed?(): void
  rememberUser?(user: string): void
  pickDirectory?(title: string): Promise<string>
  exportCreds?: {
    load(): Promise<Record<string, string>>
    save(patch: Record<string, string>): Promise<void>
  }
  slidesToPdf?(html: string, name: string): Promise<string>
  backendInfo?(): Promise<{ port: number; pid: number; dataDir: string } | null>
  quickCapture?: {
    ready(): void
    status(): Promise<{ accelerator: string; registered: boolean; reason: string }>
    readClipboard(): Promise<string>
  }
  journey?: {
    state(): Promise<{ state: 'off' | 'running' | 'paused' | 'no-permission'; today: number }>
    start(): Promise<void>
    pause(minutes?: number): Promise<void>
    resume(): Promise<void>
    stop(): Promise<void>
  }
}
