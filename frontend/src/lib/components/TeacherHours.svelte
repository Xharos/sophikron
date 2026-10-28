<script lang="ts">
	import { blockKinds, formatTeachingHours, type TimetableEvent } from '#lib/timetable';
	import { teacherSubjectHours, teacherCalendarHours } from '#lib/teacherTimetable';
	let {
		events,
		sessionMinutes,
		subjects
	}: {
		events: TimetableEvent[];
		sessionMinutes: number;
		subjects: { id: number; name: string }[];
	} = $props();
	const totals = $derived(teacherSubjectHours(events, sessionMinutes));
	const rows = $derived(teacherCalendarHours(events, sessionMinutes));
	const kinds = ['course', 'td', 'tp', 'kholle'] as const;
	const totalKinds = [...kinds, 'total'] as const;
	function subjectName(id: number | null): string {
		return subjects.find((subject) => subject.id === id)?.name ?? 'Sans matière';
	}
</script>

{#if rows.length}
	<div class="table-container">
		<table class="table is-fullwidth is-narrow is-striped hours-table">
			<caption class="has-text-left mb-2">Répartition par calendrier et matière</caption>
			<thead
				><tr>
					<th scope="col">Calendrier / promotion</th><th scope="col">Matière</th>
					{#each kinds as kind (kind)}<th scope="col">{blockKinds[kind]}</th>{/each}
					<th scope="col">Total</th>
				</tr></thead
			>
			<tbody>
				{#each rows as row (`${row.calendarId}-${row.subjectId}`)}<tr>
						<th scope="row">{row.label}</th><td>{subjectName(row.subjectId)}</td>
						{#each totalKinds as kind (kind)}<td class:has-text-weight-semibold={kind === 'total'}
								>{formatTeachingHours(row[kind])}</td
							>{/each}
					</tr>{/each}
			</tbody>
			<tfoot>
				{#each totals as row (row.subjectId)}<tr class="subject-total">
						<th scope="row" colspan="2">Total · {subjectName(row.subjectId)}</th>
						{#each totalKinds as kind (kind)}<td>{formatTeachingHours(row[kind])}</td>{/each}
					</tr>{/each}
				<tr class="grand-total"
					><th scope="row" colspan="2">Total général</th>
					{#each totalKinds as kind (kind)}<td
							>{formatTeachingHours(totals.reduce((sum, row) => sum + row[kind], 0))}</td
						>{/each}
				</tr>
			</tfoot>
		</table>
	</div>
{:else}<p role="status">Aucune séance affectée pendant cette semaine.</p>{/if}

<style>
	.hours-table td,
	.hours-table th {
		vertical-align: middle;
	}
	.hours-table td {
		white-space: nowrap;
	}
	.subject-total {
		font-size: 0.9rem;
	}
	.grand-total {
		background: var(--color-primary-soft);
		font-weight: 700;
	}
	.grand-total th,
	.grand-total td {
		border-top: 2px solid var(--color-primary);
		color: var(--color-text);
	}
</style>
