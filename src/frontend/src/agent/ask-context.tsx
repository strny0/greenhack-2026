import { createContext, useContext } from "react";

/**
 * What the agent will be looking at when the operator asks something: the hour
 * on screen, the element selected on the diagram, and whether a what-if
 * simulation is active. The composer shows it as a row of chips so the operator
 * never has to guess the agent's context, and can drop the selection from it.
 */
export interface AskContext {
  /** The hour on screen, e.g. "Mon 1 Jan, 18:00". */
  hourLabel: string;
  /** Display name of the selected diagram element, if any. */
  selectionLabel: string | null;
  /** Short label of the active simulation, if any. */
  simulationLabel: string | null;
  clearSelection: () => void;
}

export const AskContextCtx = createContext<AskContext | null>(null);

export function useAskContext(): AskContext | null {
  return useContext(AskContextCtx);
}

/** Fired when something outside the chat asks the agent a question. */
export const ASK_EVENT = "smooth-operator:ask";
