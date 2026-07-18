"use client";

import { useRef, useState } from "react";
import { FileUp, Sparkles, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type Phase = "idle" | "dragging" | "uploaded" | "prefilling";

/**
 * Drag-and-drop + "AI pre-fill" for onboarding-time COI import.
 *
 * # ASSUMPTION: parse_document (ADR 0004) isn't wired to the frontend yet, so
 * this is a visual placeholder per the task brief -- it accepts a file,
 * shows an uploading/"reading" state, then a static pre-fill skeleton rather
 * than real extracted values. Swapping in the real tool means replacing the
 * setTimeout below with an actual call to the parse_document endpoint and
 * rendering its extraction output through the same coverage-comparison
 * component already used on the run trace and review queue screens.
 */
export function ImportCoiDropzone() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [filename, setFilename] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setFilename(file.name);
    setPhase("uploaded");
    window.setTimeout(() => setPhase("prefilling"), 500);
  }

  return (
    <div className="space-y-4">
      <div
        role="button"
        tabIndex={0}
        data-testid="coi-dropzone"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setPhase("dragging"); }}
        onDragLeave={() => setPhase(filename ? "uploaded" : "idle")}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors",
          phase === "dragging" ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground/40",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.tiff"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <UploadCloud className="size-6 text-muted-foreground" />
        <p className="text-sm font-medium text-foreground">Drag a certificate here, or click to browse</p>
        <p className="text-xs text-muted-foreground">PDF, PNG, JPG, or TIFF, up to 10 MB</p>
      </div>

      {phase === "uploaded" || phase === "prefilling" ? (
        <div className="rounded-lg border border-border p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium">
            <FileUp className="size-4 text-muted-foreground" />
            {filename}
          </div>
          {phase === "uploaded" ? (
            <p className="text-sm text-muted-foreground">Uploaded. Reading the certificate…</p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Sparkles className="size-4" />
                AI pre-fill placeholder — extraction isn&apos;t wired up in this build yet
              </div>
              <div className="space-y-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-2/3" />
              </div>
              <p className="text-xs text-muted-foreground">
                Once <code className="rounded bg-muted px-1 py-0.5 font-mono">parse_document</code> is wired up, this panel will show the same parsed-vs-required comparison used on the run trace and review queue screens, ready for you to confirm before it&apos;s filed.
              </p>
            </div>
          )}
        </div>
      ) : null}

      <div className="flex justify-end">
        <Button type="button" variant="outline" disabled>
          Use this certificate
        </Button>
      </div>
    </div>
  );
}
