import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Paperclip, Send } from "lucide-react";
import { useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/form";
import { ResultView } from "@/components/result-view";
import { useApi } from "@/lib/api";
import type { RequestResult } from "@/lib/types";

interface Props {
  placeholder: string;
  examples: string[];
  allowUpload?: boolean;
}

/** Natural-language request box (+ optional document upload) that posts to the agent graph. */
export function AskPanel({ placeholder, examples, allowUpload }: Props) {
  const { raw } = useApi();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const run = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.set("query", query.trim());
      files.forEach((f) => body.append("files", f));
      return (await raw("/api/requests", { method: "POST", body })).json() as Promise<RequestResult>;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["requests"] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="space-y-3 pt-5">
          <Textarea value={query} onChange={(e) => setQuery(e.target.value)} placeholder={placeholder} maxLength={2000} />
          <div className="flex flex-wrap gap-2">
            {examples.map((ex) => (
              <button key={ex} type="button" onClick={() => setQuery(ex)} className="rounded-full border bg-secondary px-3 py-1 text-xs hover:bg-accent">
                {ex}
              </button>
            ))}
          </div>
          {files.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {files.map((f) => (
                <Badge key={f.name} variant="secondary">
                  {f.name}
                </Badge>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2">
            {allowUpload && (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  multiple
                  hidden
                  accept=".pdf,.docx,.png,.jpg,.jpeg,.txt"
                  onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                />
                <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}>
                  <Paperclip className="size-4" /> Attach documents
                </Button>
              </>
            )}
            <Button className="ml-auto" disabled={!query.trim() || run.isPending} onClick={() => run.mutate()}>
              {run.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
              {run.isPending ? "Agents working…" : "Run"}
            </Button>
          </div>
        </CardContent>
      </Card>
      {run.isError && <p className="text-sm text-destructive">{(run.error as Error).message}</p>}
      {run.data && <ResultView result={run.data} />}
    </div>
  );
}
