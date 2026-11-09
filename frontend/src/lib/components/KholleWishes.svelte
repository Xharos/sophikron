<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { onMount, untrack, type Snippet } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import SubjectTag from './SubjectTag.svelte';
	import RoleBadges from './RoleBadges.svelte';
	import { timetableCommand } from '#lib/timetableClient';
	import {
		allocatedWishSubjects,
		completeWishEntries,
		compareWishPeople,
		wishBalance,
		wishSessions,
		type KholleWishes,
		type KholleWishPerson,
		type KholleWishEntry
	} from '#lib/kholleWishes';

	let {
		initial,
		needs,
		onsaved,
		onvalidity,
		ondirty,
		onnotice,
		canWrite = true,
		showHeading = true,
		saveEntries,
		startEditing = false,
		guardNavigation = true,
		subjectExtras
	}: {
		initial: KholleWishes;
		needs: Record<number, number> | null;
		onsaved?: () => void | Promise<void>;
		onvalidity?: (valid: boolean) => void;
		ondirty?: (dirty: boolean) => void;
		onnotice?: (message: string) => void;
		canWrite?: boolean;
		showHeading?: boolean;
		saveEntries?: (entries: KholleWishEntry[]) => Promise<KholleWishes>;
		startEditing?: boolean;
		guardNavigation?: boolean;
		subjectExtras?: Snippet<[subject: KholleWishes['subjects'][number]]>;
	} = $props();
	let saved = $state<KholleWishes>(untrack(() => initial));
	let editing = $state(
		untrack(() => {
			const visible = allocatedWishSubjects(initial.subjects, needs);
			return (
				startEditing ||
				(canWrite &&
					visible.length > 0 &&
					visible.every((subject) => subject.staff.every((person) => person.sessions === null)))
			);
		})
	);
	let busy = $state(false);
	let values = $state<Record<string, string>>(
		untrack(() =>
			Object.fromEntries(
				initial.subjects.flatMap((subject) =>
					subject.staff.map((person) => [
						`${subject.id}-${person.id}`,
						person.sessions === null ? '' : String(person.sessions)
					])
				)
			)
		)
	);
	let message = $state('');
	onMount(() => onnotice?.(''));
	const key = (subject: number, person: number): string => `${subject}-${person}`;
	const number = (value: number): string =>
		value.toLocaleString('fr-FR', { maximumFractionDigits: 2 });
	const subjects = $derived(
		allocatedWishSubjects(saved.subjects, needs).map((subject) => ({
			...subject,
			staff: [...subject.staff].sort(compareWishPeople)
		}))
	);
	const entries = $derived(
		subjects.flatMap((subject) =>
			subject.staff.map((person) => ({
				user_id: person.id,
				subject_id: subject.id,
				sessions: editing ? wishSessions(values[key(subject.id, person.id)] ?? '') : person.sessions
			}))
		)
	);
	const invalid = $derived(entries.some((entry) => entry.sessions === undefined));
	const dirty = $derived(
		editing &&
			subjects.some((subject) =>
				subject.staff.some(
					(person) =>
						(values[key(subject.id, person.id)] ?? '') !==
						(person.sessions === null ? '' : String(person.sessions))
				)
			)
	);
	const people = $derived.by(() => {
		const result = new SvelteMap<
			number,
			Omit<KholleWishPerson, 'sessions'> & {
				total: number;
				missing: number;
				subjects: KholleWishes['subjects'];
			}
		>();
		for (const subject of subjects)
			for (const person of subject.staff) {
				const row = result.get(person.id) ?? {
					id: person.id,
					name: person.name,
					first_name: person.first_name,
					last_name: person.last_name,
					roles: person.roles,
					subjects: [],
					total: 0,
					missing: 0
				};
				const value = entries.find(
					(entry) => entry.user_id === person.id && entry.subject_id === subject.id
				)?.sessions;
				row.total += ((value ?? 0) / (subject.cycle_weeks ?? 2)) * 2;
				row.subjects.push(subject);
				if (value === null || value === undefined) row.missing++;
				result.set(person.id, row);
			}
		return [...result.values()].sort(compareWishPeople);
	});
	const total = $derived(
		entries.reduce(
			(sum, entry) =>
				sum +
				((entry.sessions ?? 0) /
					(subjects.find((s) => s.id === entry.subject_id)?.cycle_weeks ?? 2)) *
					2,
			0
		)
	);
	const missing = $derived(entries.filter((entry) => entry.sessions === null).length);
	$effect(() => {
		ondirty?.(dirty || busy);
		return () => ondirty?.(false);
	});
	$effect(() => {
		onvalidity?.(!invalid && !busy);
	});

	beforeNavigate((navigation) => {
		if (!guardNavigation) return;
		if (
			busy ||
			(dirty && !window.confirm('Abandonner les modifications des souhaits de service ?'))
		)
			navigation.cancel();
	});
	function beforeUnload(event: BeforeUnloadEvent): void {
		if (guardNavigation && (dirty || busy)) {
			event.preventDefault();
			event.returnValue = '';
		}
	}
	function start(): void {
		if (!canWrite) return;
		values = Object.fromEntries(
			subjects.flatMap((subject) =>
				subject.staff.map((person) => [
					key(subject.id, person.id),
					person.sessions === null ? '' : String(person.sessions)
				])
			)
		);
		message = '';
		onnotice?.('');
		editing = true;
	}
	export async function save(): Promise<boolean> {
		if (busy || invalid || !canWrite) return false;
		if (!editing) return true;
		busy = true;
		message = '';
		onnotice?.('');
		try {
			const submitted = completeWishEntries(saved.subjects, entries as KholleWishEntry[]);
			saved = saveEntries
				? await saveEntries(submitted)
				: await timetableCommand<KholleWishes>(`kholloscope/${saved.school_year}/wishes`, 'PUT', {
						expected_revision: saved.revision,
						entries: submitted
					});
			editing = false;
			onnotice?.('Enregistrement effectué.');
			await onsaved?.();
			return true;
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
			return false;
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window onbeforeunload={beforeUnload} />

<section class="wishes" aria-labelledby="wishes-title" aria-busy={busy}>
	<header class="wishes-heading">
		<div>
			{#if showHeading}<h2 id="wishes-title" class="title is-4">Souhaits de service</h2>{:else}<span
					id="wishes-title"
					class="is-sr-only">Souhaits de service</span
				>{/if}
			<p class="intro">
				Un engagement exact par matière sur le cycle indiqué. La durée du cycle s’adapte à la
				fréquence des khôlles.
			</p>
		</div>
		{#if canWrite && !editing}<button
				class="button is-small is-light"
				onclick={start}
				disabled={!entries.length}>Modifier</button
			>{/if}
	</header>
	<div class="wish-summary">
		<div><span>Intervenants</span><strong>{people.length}</strong></div>
		<div><span>Équivalent / 2 semaines</span><strong>{number(total)}</strong></div>
		<div><span>Moyenne / semaine</span><strong>{number(total / 2)}</strong></div>
		<div><span>Souhaits à renseigner</span><strong>{missing}</strong></div>
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if subjects.length && saved.unassigned.length}
		<p class="notification is-warning is-light">
			Sans matière active : {saved.unassigned.map((person) => person.name).join(', ')}. Affectez une
			matière à ces intervenants depuis leur profil pour saisir leurs souhaits.
		</p>
	{/if}
	<form onsubmit={(event) => event.preventDefault()}>
		{#each subjects as subject (subject.id)}
			{@const subjectEntries = entries.filter((entry) => entry.subject_id === subject.id)}
			{@const balance = wishBalance(
				subjectEntries.map((entry) => entry.sessions ?? null),
				needs === null ? null : (needs[subject.id] ?? 0),
				subject.cycle_weeks ?? 2
			)}
			<article class="subject-panel" style:--subject-color={subject.color}>
				{#if subject.previous_cycle_weeks && subject.previous_cycle_weeks !== subject.cycle_weeks}<p
						class="notification is-info is-light"
					>
						Cycle passé de {subject.previous_cycle_weeks} à {subject.cycle_weeks} semaines. Les anciens
						engagements sont convertis proportionnellement ; les valeurs non entières doivent être renseignées
						à nouveau.
					</p>{/if}
				<header class="subject-heading">
					<div class="subject-title">
						<SubjectTag {subject} />
						<span class="subject-need"
							>Besoin moyen / {subject.cycle_weeks ?? 2} semaines :
							<strong
								>{needs === null
									? '—'
									: number((needs[subject.id] ?? 0) * (subject.cycle_weeks ?? 2))} séances</strong
							></span
						>
					</div>
					<div class="subject-status">
						<span class="subject-gap"
							>Écart : <strong
								>{balance.difference === null
									? '—'
									: `${balance.difference > 0 ? '+' : ''}${number(balance.difference * (subject.cycle_weeks ?? 2))}`}
								/ {subject.cycle_weeks ?? 2} semaines</strong
							></span
						>
						<span class="balance" class:balanced={balance.label === 'Volumes équilibrés'}
							>{balance.label}</span
						>
					</div>
				</header>
				{#if subject.staff.length}
					<div class="table-container">
						<table class="table is-fullwidth wish-table">
							<caption class="is-sr-only">Souhaits de service en {subject.name}</caption>
							<colgroup
								><col class="person-column" /><col class="role-column" /><col
									class="volume-column"
								/><col class="volume-column" /></colgroup
							>
							<thead
								><tr
									><th scope="col">Intervenant</th><th scope="col">Rôle</th><th
										scope="col"
										class="numeric">Séances / {subject.cycle_weeks ?? 2} sem.</th
									><th scope="col" class="numeric">Moyenne / sem.</th></tr
								></thead
							>
							<tbody>
								{#each subject.staff as person (person.id)}
									{@const value = entries.find(
										(entry) => entry.subject_id === subject.id && entry.user_id === person.id
									)?.sessions}
									<tr>
										<th scope="row"
											><span class="person"
												><span class="avatar" aria-hidden="true"
													>{person.first_name.slice(0, 1)}{person.last_name.slice(0, 1)}</span
												><span>{person.first_name} <strong>{person.last_name}</strong></span></span
											></th
										>
										<td><RoleBadges roles={person.roles} /></td>
										<td class="numeric"
											>{#if editing}<input
													class="input is-small session-input"
													type="number"
													min="0"
													max="1000"
													step="1"
													placeholder="Non renseigné"
													aria-label={`Séances sur ${(subject.cycle_weeks ?? 2) === 2 ? 'deux' : subject.cycle_weeks} semaines — ${person.name} — ${subject.name}`}
													aria-invalid={value === undefined}
													value={values[key(subject.id, person.id)] ?? ''}
													oninput={(event) => {
														values[key(subject.id, person.id)] = event.currentTarget.value;
													}}
													disabled={busy || !canWrite}
												/>{:else if person.sessions === null}<span class="unfilled"
													>Non renseigné</span
												>{:else}<strong>{number(person.sessions)}</strong>{/if}</td
										>
										<td class="numeric average"
											>{value === null || value === undefined
												? '—'
												: number(value / (subject.cycle_weeks ?? 2))}</td
										>
									</tr>
								{/each}
							</tbody>
							<tfoot
								><tr
									><th scope="row" colspan="2">Total {subject.name}</th><td class="numeric"
										>{number(balance.total)}</td
									><td class="numeric">{number(balance.total / (subject.cycle_weeks ?? 2))}</td></tr
								></tfoot
							>
						</table>
					</div>
				{:else}<p class="empty">Aucun enseignant ou khôlleur associé à cette matière.</p>{/if}
				{#if subjectExtras}<div class="subject-extras">{@render subjectExtras(subject)}</div>{/if}
			</article>
		{:else}<p class="notification is-light">
				Aucune matière avec un volume de khôlles alloué pour cette année. Configurez les khôlles des
				promotions pour saisir les souhaits de service.
			</p>{/each}
	</form>
	{#if people.length}
		<details class="person-totals">
			<summary>Totaux par intervenant · toutes matières confondues</summary>
			<div class="table-container recap-container">
				<table class="table is-fullwidth wish-table recap-table">
					<caption class="is-sr-only"
						>Totaux des souhaits par intervenant, rôles et matières</caption
					>
					<colgroup
						><col style="width:28%" /><col style="width:20%" /><col style="width:24%" /><col
							style="width:14%"
						/><col style="width:14%" /></colgroup
					>
					<thead
						><tr
							><th scope="col">Intervenant</th><th scope="col">Rôle</th><th scope="col">Matières</th
							><th scope="col" class="numeric">Séances / 2 sem. (équivalent)</th><th
								scope="col"
								class="numeric">Moyenne / sem.</th
							></tr
						></thead
					>
					<tbody
						>{#each people as person (person.id)}
							<tr style:--subject-color={person.subjects[0].color}>
								<th scope="row"
									><span class="person"
										><span class="avatar" aria-hidden="true"
											>{person.first_name.slice(0, 1)}{person.last_name.slice(0, 1)}</span
										><span
											>{person.first_name}
											<strong>{person.last_name}</strong>{#if person.missing}<small
													class="incomplete">Souhaits incomplets</small
												>{/if}</span
										></span
									></th
								>
								<td><RoleBadges roles={person.roles} /></td>
								<td
									><div class="recap-subjects">
										{#each person.subjects as subject (subject.id)}<SubjectTag {subject} />{/each}
									</div></td
								>
								<td class="numeric recap-total"><strong>{number(person.total)}</strong></td>
								<td class="numeric average">{number(person.total / 2)}</td>
							</tr>
						{/each}</tbody
					>
				</table>
			</div>
		</details>
	{/if}
	{#if editing}
		<div class="save-bar">
			<p>
				{invalid
					? 'Saisissez des entiers entre 0 et 1 000, ou laissez les champs vides.'
					: dirty
						? 'Modifications non enregistrées'
						: 'Aucune modification'}
			</p>
		</div>
	{/if}
</section>

<style>
	.subject-extras {
		padding: 1.25rem;
		border-top: var(--border-thin);
	}
	.wishes {
		margin: 1rem 0 2rem;
		color: var(--color-ink);
	}
	.wishes-heading,
	.subject-heading,
	.save-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.wishes-heading {
		margin-bottom: 1rem;
	}
	.wishes-heading .title {
		margin-bottom: 0.5rem;
	}
	.intro {
		color: var(--color-muted);
		font-size: 0.85rem;
		line-height: 1.6;
	}
	.wish-summary {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		border: var(--border-thin);
		border-radius: var(--radius-panel);
		background: var(--color-paper);
		overflow: hidden;
	}
	.wish-summary > div {
		padding: 1.1rem 1.3rem;
	}
	.wish-summary span {
		display: block;
		color: var(--color-muted);
		font-size: 0.75rem;
		margin-bottom: 0.4rem;
	}
	.wish-summary strong {
		font-size: 1.5rem;
		font-variant-numeric: tabular-nums;
	}
	.subject-panel {
		margin: 1.25rem 0;
		border: var(--border-thin);
		border-top: 3px solid var(--subject-color);
		border-radius: var(--radius-panel);
		overflow: hidden;
		background: var(--color-surface);
	}
	.subject-heading {
		padding: 1rem 1.25rem;
		background: color-mix(in srgb, var(--subject-color) 7%, var(--color-surface));
	}
	.subject-title,
	.subject-status {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.subject-need,
	.subject-gap {
		font-size: 0.8rem;
		font-variant-numeric: tabular-nums;
	}
	.subject-need {
		background: var(--color-surface);
		border: 1px solid color-mix(in srgb, var(--subject-color) 35%, var(--color-border));
		padding: 0.4rem 0.7rem;
		border-radius: 8px;
	}
	.subject-need strong {
		font-size: 0.95rem;
	}
	.subject-gap {
		color: var(--color-muted);
	}
	.subject-gap strong {
		color: var(--color-ink);
	}
	.balance {
		font-size: 0.75rem;
		font-weight: 600;
		padding: 0.3rem 0.7rem;
		border-radius: 999px;
		background: var(--color-paper);
		border: var(--border-thin);
	}
	.balance.balanced {
		color: var(--color-success);
		background: var(--color-success-soft);
	}
	.table-container {
		margin: 0;
	}
	.wish-table {
		table-layout: fixed;
		margin: 0;
		min-width: 650px;
		background: transparent;
		font-size: 0.85rem;
	}
	.person-column {
		width: 40%;
	}
	.role-column {
		width: 24%;
	}
	.volume-column {
		width: 18%;
	}
	.wish-table th,
	.wish-table td {
		padding: 0.9rem 1.25rem;
		vertical-align: middle;
		border-color: var(--color-border);
		color: var(--color-ink);
	}
	.wish-table thead th {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--color-muted);
	}
	.wish-table tbody th {
		font-weight: 400;
	}
	.wish-table tfoot {
		background: var(--color-paper);
		font-weight: 700;
	}
	.wish-table .numeric {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.person {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		overflow-wrap: anywhere;
	}
	.avatar {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2.1rem;
		height: 2.1rem;
		flex: none;
		border-radius: 50%;
		background: color-mix(in srgb, var(--subject-color) 13%, var(--color-surface));
		font-size: 0.7rem;
		font-weight: 700;
	}
	.unfilled {
		color: var(--color-muted);
		font-size: 0.75rem;
	}
	.session-input {
		width: 9rem;
		max-width: 100%;
		text-align: right;
	}
	.session-input[aria-invalid='true'] {
		border-color: var(--color-danger);
	}
	.average {
		font-weight: 600;
	}
	.empty {
		padding: 1.25rem;
		color: var(--color-muted);
		font-size: 0.85rem;
	}
	.save-bar {
		padding: 1.25rem;
		margin: 1rem 0;
		border: var(--border-thin);
		border-radius: var(--radius-panel);
	}
	.save-bar p {
		font-size: 0.8rem;
		color: var(--color-muted);
	}
	.person-totals {
		margin-top: 1.5rem;
		border: var(--border-thin);
		border-radius: var(--radius-panel);
		padding: 1rem 1.25rem;
		font-size: 0.8rem;
	}
	.person-totals summary {
		cursor: pointer;
		font-weight: 600;
	}
	.recap-container {
		margin-top: 1rem;
	}
	.recap-table {
		min-width: 850px;
	}
	.recap-table tbody th {
		border-left: 3px solid var(--subject-color);
	}
	.recap-subjects {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.recap-total {
		background: color-mix(in srgb, var(--subject-color) 9%, var(--color-surface));
	}
	.incomplete {
		display: block;
		color: var(--color-muted);
		font-size: 0.7rem;
		margin-top: 0.25rem;
	}
	@media (max-width: 700px) {
		.wish-summary {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
