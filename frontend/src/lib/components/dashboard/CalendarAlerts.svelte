<script lang="ts">
	import { resolve } from '$app/paths';
	import type { TimetableCatalog, TimetableBoard } from '#lib/timetable';
	import { timetableDiagnostics, timetableWarningColor } from '#lib/timetableWarnings';
	import TimetableChecksButton from '../TimetableChecksButton.svelte';
	let {
		catalog,
		error = '',
		revision = 0
	}: { catalog: TimetableCatalog | null; error?: string; revision?: number } = $props();
	let rows = $state<
		Record<
			number,
			{ count: number; color: 'is-success' | 'is-warning' | 'is-danger'; error?: string }
		>
	>({});
	const calendars = $derived(catalog?.calendars.filter((c) => !c.is_archived) ?? []);
	$effect(() => {
		const selected = calendars;
		const today = catalog?.today ?? '';
		void revision;
		const controller = new AbortController();
		rows = {};
		void Promise.all(
			selected.map(async (calendar) => {
				try {
					const response = await fetch(
						resolve('/timetable/data') + '?calendar_ids=' + calendar.id,
						{ signal: controller.signal, cache: 'no-store' }
					);
					if (!response.ok) throw new Error('Alertes indisponibles');
					const board = (await response.json()) as TimetableBoard;
					const checks = timetableDiagnostics(board, today);
					if (!controller.signal.aborted)
						rows = {
							...rows,
							[calendar.id]: { count: checks.length, color: timetableWarningColor(checks) }
						};
				} catch {
					if (!controller.signal.aborted)
						rows = {
							...rows,
							[calendar.id]: { count: 0, color: 'is-warning', error: 'Alertes indisponibles' }
						};
				}
			})
		);
		return () => controller.abort();
	});
</script>

<section class="workspace-panel calendar-alerts" aria-label="Alertes des calendriers">
	<p class="eyebrow">Calendriers</p>
	<h3 class="title is-6 mb-3">Points à vérifier</h3>
	{#if error || !catalog}<p role="status">{error || 'Les calendriers sont indisponibles.'}</p>
	{:else if !calendars.length}<p class="muted">Aucun calendrier actif.</p>
	{:else}
		{#each calendars as calendar (calendar.id)}
			<div class="calendar-row">
				<span>{calendar.name}</span>
				{#if rows[calendar.id]?.error}<small role="status">{rows[calendar.id].error}</small>
				{:else if rows[calendar.id]}<TimetableChecksButton
						count={rows[calendar.id].count}
						color={rows[calendar.id].color}
						href={resolve('/timetable/[id]', { id: String(calendar.id) }) + '?checks=1'}
					/>
				{:else}<small role="status">Chargement…</small>{/if}
			</div>
		{/each}
	{/if}
</section>

<style>
	.calendar-alerts {
		min-width: 0;
	}
	.calendar-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		padding: 0.6rem 0;
		border-bottom: var(--border-thin);
	}
	.calendar-row:last-child {
		border-bottom: 0;
	}
	.calendar-row span {
		overflow-wrap: anywhere;
	}
</style>
