/**
 * The query layer over the gateway.
 *
 * Engine state is cached here and invalidated by the core's events, so a change made by an AI
 * client or the CLI refreshes the workbench the same way one made here does. Neither this cache
 * nor any component becomes a second authoritative copy of the project.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect } from "react";

import { useGateway } from "../../app/providers.tsx";
import type {
  ActivityEntry,
  AutomationPolicyValue,
  DesktopSettings,
  LayerTreeMode,
  ProjectTarget,
  ProjectUIMetadataValue,
  RenderStatus,
} from "../../gateway/index.ts";
import type {
  HistoryReport,
  HitTestReport,
  LayerTreeReport,
  ProjectPolicyReport,
  ProjectSnapshotReport,
  ProjectUIMetadataReport,
  ProposalListReport,
} from "../../contracts/index.ts";

export const projectKeys = {
  engine: ["engine-state"] as const,
  snapshot: ["project-snapshot"] as const,
  target: ["active-target"] as const,
  layerTree: (mode: LayerTreeMode) => ["layer-tree", mode] as const,
  render: ["render-status"] as const,
  activity: ["activity"] as const,
  settings: ["settings"] as const,
  policy: ["project-policy"] as const,
  uiMetadata: ["project-ui-metadata"] as const,
  proposals: ["proposals"] as const,
  history: ["editor-history"] as const,
};

/**
 * Keep the cache honest by listening to the core rather than polling.
 *
 * Each event invalidates only what it can have changed: a render event must not re-fetch the
 * layer tree, or every frame of a live render would refetch the whole project.
 */
export function useDesktopEvents(): void {
  const gateway = useGateway();
  const queryClient = useQueryClient();

  useEffect(
    () =>
      gateway.subscribe((event) => {
        switch (event.type) {
          case "engine":
            void queryClient.invalidateQueries({ queryKey: projectKeys.engine });
            break;
          case "project":
            void queryClient.invalidateQueries({ queryKey: projectKeys.snapshot });
            void queryClient.invalidateQueries({ queryKey: ["layer-tree"] });
            void queryClient.invalidateQueries({ queryKey: projectKeys.proposals });
            // Undo availability belongs to the project's revision, so any project event can
            // change it — including one this window did not cause.
            void queryClient.invalidateQueries({ queryKey: projectKeys.history });
            break;
          case "render":
            queryClient.setQueryData(projectKeys.render, event.render);
            break;
          case "activity":
            void queryClient.invalidateQueries({ queryKey: projectKeys.activity });
            break;
          case "settings":
            queryClient.setQueryData(projectKeys.settings, event.settings);
            break;
        }
      }),
    [gateway, queryClient],
  );
}

export function useProjectSnapshot(): UseQueryResult<ProjectSnapshotReport> {
  const gateway = useGateway();
  // No project open is an expected state, not a failure worth retrying.
  return useQuery({
    queryKey: projectKeys.snapshot,
    queryFn: () => gateway.projectSnapshot(),
    retry: false,
  });
}

export function useActiveTarget(): UseQueryResult<ProjectTarget> {
  const gateway = useGateway();
  return useQuery({ queryKey: projectKeys.target, queryFn: () => gateway.activeTarget() });
}

export function useLayerTree(mode: LayerTreeMode): UseQueryResult<LayerTreeReport> {
  const gateway = useGateway();
  return useQuery({
    queryKey: projectKeys.layerTree(mode),
    queryFn: () => gateway.layerTree(mode),
    retry: false,
  });
}

export function useRenderStatus(): UseQueryResult<RenderStatus> {
  const gateway = useGateway();
  return useQuery({ queryKey: projectKeys.render, queryFn: () => gateway.renderStatus() });
}

export function useActivity(): UseQueryResult<ReadonlyArray<ActivityEntry>> {
  const gateway = useGateway();
  return useQuery({ queryKey: projectKeys.activity, queryFn: () => gateway.activity() });
}

export function useEditorHistory(): UseQueryResult<HistoryReport> {
  const gateway = useGateway();
  // No project open means no history; that is a state, not a failure worth retrying.
  return useQuery({
    queryKey: projectKeys.history,
    queryFn: () => gateway.editorHistory(),
    retry: false,
  });
}

export function useSettings(): UseQueryResult<DesktopSettings> {
  const gateway = useGateway();
  return useQuery({ queryKey: projectKeys.settings, queryFn: () => gateway.settings() });
}

export function usePolicy(): UseQueryResult<ProjectPolicyReport> {
  const gateway = useGateway();
  return useQuery({ queryKey: projectKeys.policy, queryFn: () => gateway.policy(), retry: false });
}

export function useUiMetadata(): UseQueryResult<ProjectUIMetadataReport> {
  const gateway = useGateway();
  return useQuery({
    queryKey: projectKeys.uiMetadata,
    queryFn: () => gateway.uiMetadata(),
    retry: false,
  });
}

export function useProposals(): UseQueryResult<ProposalListReport> {
  const gateway = useGateway();
  return useQuery({
    queryKey: projectKeys.proposals,
    queryFn: () => gateway.proposals(),
    retry: false,
  });
}

export function useOpenProject() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => gateway.openProject(path),
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

/** Close the open project and forget everything cached about it.
 *
 * The engine dropped the session as soon as it was asked; the window kept showing the project
 * because nothing invalidated the snapshot, so the button read as doing nothing at all.
 */
export function useCloseProject() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => gateway.closeProject(),
    // Reset rather than invalidated: invalidating refetches, and a refetch that fails because
    // no project is open leaves the last successful snapshot in place, so the workbench went on
    // showing the project it had just closed. Resetting clears every observer's data first,
    // which is what "there is no project now" actually means.
    onSuccess: () => queryClient.resetQueries(),
  });
}

/** Open whatever the folder chooser returns; a cancelled dialog opens nothing. */
export function useBrowseForProject() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const path = await gateway.chooseProjectDirectory();
      return path === null ? null : gateway.openProject(path);
    },
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

export function useSetActiveTarget() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (target: ProjectTarget) => gateway.setActiveTarget(target),
    onSuccess: (target) => {
      queryClient.setQueryData(projectKeys.target, target);
      void queryClient.invalidateQueries({ queryKey: ["layer-tree"] });
      void queryClient.invalidateQueries({ queryKey: projectKeys.render });
    },
  });
}

export function useRequestRender() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => gateway.requestRender(),
    onSuccess: (status) => queryClient.setQueryData(projectKeys.render, status),
  });
}

export function useHitTest() {
  const gateway = useGateway();
  return useMutation({
    mutationFn: ({ xPt, yPt }: { xPt: number; yPt: number }): Promise<HitTestReport> =>
      gateway.hitTest(xPt, yPt),
  });
}

export function useUpdateSettings() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<DesktopSettings>) => gateway.updateSettings(patch),
    onSuccess: (settings) => queryClient.setQueryData(projectKeys.settings, settings),
  });
}

export function useSetPolicy() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (policy: AutomationPolicyValue) => gateway.setPolicy(policy),
    onSuccess: (report) => queryClient.setQueryData(projectKeys.policy, report),
  });
}

export function useSetUiMetadata() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (metadata: ProjectUIMetadataValue) => gateway.setUiMetadata(metadata),
    onSuccess: (report) => queryClient.setQueryData(projectKeys.uiMetadata, report),
  });
}

export function useProposalActions() {
  const gateway = useGateway();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: projectKeys.proposals });
  return {
    approve: useMutation({
      mutationFn: (commandId: string) => gateway.approveProposal(commandId),
      onSuccess: () => void refresh(),
    }),
    reject: useMutation({
      mutationFn: ({ commandId, reason }: { commandId: string; reason: string }) =>
        gateway.rejectProposal(commandId, reason),
      onSuccess: () => void refresh(),
    }),
  };
}
