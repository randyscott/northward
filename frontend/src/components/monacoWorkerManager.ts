// A drop-in for monaco-worker-manager's createWorkerManager (used by monaco-yaml), updated for Monaco 0.57:
// `editor.createWebWorker` now takes the Worker itself, which receives a throwaway message and then its create data
// (the protocol Monaco's own language workers use). The original passes the old `moduleId`/`label` options, so
// Monaco silently falls back to its plain editor worker and the YAML features fail. Wired in by vite.config.ts.
import type * as Monaco from "monaco-editor";

interface Options<CreateData> {
  createData: CreateData;
  label: string;
  moduleId: string;
  interval?: number;
  stopWhenIdleFor?: number;
}

export function createWorkerManager<T extends object, CreateData>(monaco: typeof Monaco, options: Options<CreateData>) {
  let { createData } = options;
  const { label, moduleId, interval = 30_000, stopWhenIdleFor = 120_000 } = options;
  let worker: Monaco.editor.MonacoWebWorker<T> | undefined;
  let lastUsedTime = 0;
  let disposed = false;

  const stopWorker = () => {
    worker?.dispose();
    worker = undefined;
  };
  const intervalId = setInterval(() => {
    if (worker && Date.now() - lastUsedTime > stopWhenIdleFor) stopWorker();
  }, interval);

  return {
    dispose() {
      disposed = true;
      clearInterval(intervalId);
      stopWorker();
    },
    getWorker(...resources: Monaco.Uri[]): Promise<T> {
      if (disposed) throw new Error("Worker manager has been disposed");
      lastUsedTime = Date.now();
      if (!worker) {
        const raw = self.MonacoEnvironment!.getWorker!(moduleId, label) as Worker;
        raw.postMessage("ignore");
        raw.postMessage(createData);
        worker = monaco.editor.createWebWorker<T>({ worker: raw });
      }
      return worker.withSyncedResources(resources);
    },
    updateCreateData(newCreateData: CreateData) {
      createData = newCreateData;
      stopWorker();
    },
  };
}
