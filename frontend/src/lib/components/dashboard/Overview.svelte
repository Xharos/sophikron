<script lang="ts">
	import StatisticsPanel from '../statistics/StatisticsPanel.svelte';
	import ActivityJournal from './ActivityJournal.svelte';
	import CalendarAlerts from './CalendarAlerts.svelte';
	import type { TimetableCatalog } from '#lib/timetable';
	let {
		calendarCatalog = null,
		calendarError = ''
	}: { calendarCatalog?: TimetableCatalog | null; calendarError?: string } = $props();
	let journalRevision = $state(0);
</script>

<StatisticsPanel showIntro={false} onrefresh={() => (journalRevision += 1)}>
	{#snippet maintenanceExtras()}<CalendarAlerts
			catalog={calendarCatalog}
			error={calendarError}
			revision={journalRevision}
		/>{/snippet}
</StatisticsPanel>
<ActivityJournal revision={journalRevision} />
