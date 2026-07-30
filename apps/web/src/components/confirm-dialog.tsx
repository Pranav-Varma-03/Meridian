"use client";

import { useEffect, useRef } from "react";

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "Confirm",
  pending = false,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  children: React.ReactNode;
  confirmLabel?: string;
  pending?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const cancelAction = useRef(onCancel);
  const pendingAction = useRef(pending);
  useEffect(() => {
    cancelAction.current = onCancel;
  }, [onCancel]);
  useEffect(() => {
    pendingAction.current = pending;
  }, [pending]);
  useEffect(() => {
    if (!open) return;
    trigger.current = document.activeElement as HTMLElement;
    cancel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (pendingAction.current) return;
        event.preventDefault();
        cancelAction.current();
      }
      if (event.key === "Tab") {
        if (pendingAction.current) return;
        const movingBackwards = event.shiftKey;
        if (
          (movingBackwards && document.activeElement === cancel.current) ||
          (!movingBackwards && document.activeElement === confirm.current)
        ) {
          event.preventDefault();
          (movingBackwards ? confirm.current : cancel.current)?.focus();
        }
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      trigger.current?.focus();
    };
  }, [open]);
  if (!open) return null;
  return (
    <div
      aria-describedby="confirm-dialog-description"
      aria-labelledby="confirm-dialog-title"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/30 p-4"
      role="dialog"
    >
      <section className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-lg">
        <h2 className="text-lg font-semibold" id="confirm-dialog-title">
          {title}
        </h2>
        <div className="mt-2 text-sm text-muted-foreground" id="confirm-dialog-description">
          {children}
        </div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button
            className="rounded border border-border px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={pending}
            onClick={onCancel}
            ref={cancel}
            type="button"
          >
            Cancel
          </button>
          <button
            aria-busy={pending || undefined}
            className="rounded bg-primary px-3 py-2 text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
            disabled={pending}
            onClick={onConfirm}
            ref={confirm}
            type="button"
          >
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
