<script lang="ts">
	import { invalidateAll, beforeNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack, tick } from 'svelte';
	import { timetableCommand } from '#lib/timetableClient';
	import {
		groupedRevisionChanges,
		isRevisionMonday,
		revisionChange,
		type RevisionView
	} from '#lib/kholloscopeRevision';
	import type { KholleWishes as Wishes, KholleWishEntry } from '#lib/kholleWishes';
	import { roomSelectionKey } from '#lib/kholleWishes';
	import type { GeneratedSession } from '#lib/kholloscopeGeneration';
	import type { TimetableCatalog } from '#lib/timetable';
	import KholleWishes from './KholleWishes.svelte';
	import KholleRoomSelection from './KholleRoomSelection.svelte';
	import SubjectTag from './SubjectTag.svelte';
	import Icon from './Icon.svelte';
	import Modal from './Modal.svelte';
	let {
		initial,
		year,
		catalog,
		canWrite
	}: {
		initial: RevisionView;
		year: number;
		catalog: TimetableCatalog;
		canWrite: boolean;
	} = $props();
	let view = $state.raw(untrack(() => initial));
	let selected = $state<number[]>(untrack(() => initial.subjects.map((s) => s.id)));
	let effectiveOn = $state(untrack(() => initial.next_monday));
	let temporaryLeave = $state(false),
		returnOn = $state('');
	let busy = $state(false),
		error = $state(''),
		confirming = $state(false);
	let allowMoves = $state(untrack(() => initial.branch?.allow_moves ?? false));
	let rooms = $state<Record<number, number[]>>(untrack(() => initial.branch?.rooms ?? {}));
	let proposedDate = $state(
		untrack(() =>
			initial.branch && initial.branch.effective_on >= initial.next_monday
				? initial.branch.effective_on
				: initial.next_monday
		)
	);
	let editor: KholleWishes | undefined = $state();
	let editorDirty = $state(false),
		editorValid = $state(true);
	let submitted = $state<KholleWishEntry[] | null>(null);
	let logElement: HTMLPreElement | undefined = $state();
	const branch = $derived(view.branch);
	const active = $derived(branch?.status === 'queued' || branch?.status === 'running');
	const subjects = $derived(
		view.subjects.filter((s) =>
			(branch?.subject_ids ?? (branch ? [branch.subject_id] : selected)).includes(s.id)
		)
	);
	const expired = $derived(!!branch && branch.effective_on < view.next_monday);
	const needs = $derived(
		Object.fromEntries(
			subjects.map((s) => [
				s.id,
				Math.max(s.required_service / (s.cycle_weeks ?? 2), Number.EPSILON)
			])
		)
	);
	const wishInitial: Wishes = $derived({
		school_year: year,
		revision: branch?.revision ?? '',
		unassigned: [],
		subjects: subjects.map((s) => ({
			...s,
			staff: s.staff.map((p) => ({
				...p,
				sessions:
					branch?.wishes.find(
						(w) => (w.subject_id ?? branch.subject_id) === s.id && w.user_id === p.id
					)?.sessions ?? p.sessions
			}))
		}))
	});
	const dirty = $derived(
		editorDirty ||
			!!submitted ||
			(!!branch &&
				!branch.closed &&
				(allowMoves !== branch.allow_moves ||
					proposedDate !== branch.effective_on ||
					roomSelectionKey(rooms) !== roomSelectionKey(branch.rooms ?? {})))
	);
	const changes = $derived(groupedRevisionChanges(branch?.result?.changes ?? []));
	const logText = $derived(branch?.logs.join('\n') ?? '');
	$effect(() => {
		if (logText && logElement)
			void tick().then(() => {
				if (logElement) logElement.scrollTop = logElement.scrollHeight;
			});
	});
	beforeNavigate((n) => {
		if (busy || (dirty && !window.confirm('Abandonner les modifications de la proposition ?')))
			n.cancel();
	});
	async function refresh(): Promise<void> {
		const response = await fetch(
			resolve('/timetable/kholloscope/data') + '?school_year=' + year + '&kind=revision'
		);
		const body = await response.json();
		if (!response.ok) throw new Error(body.message ?? 'Lecture impossible.');
		view = body as RevisionView;
		allowMoves = view.branch?.allow_moves ?? false;
		rooms = view.branch?.rooms ?? {};
		proposedDate =
			view.branch && view.branch.effective_on >= view.next_monday
				? view.branch.effective_on
				: view.next_monday;
		submitted = null;
		editorDirty = false;
	}
	$effect(() => {
		if (!active) return;
		const timer = setInterval(() => {
			if (!busy)
				void refresh().catch((e) => {
					error = String(e);
				});
		}, 1500);
		return () => clearInterval(timer);
	});
	async function saveWishes(entries: KholleWishEntry[]): Promise<Wishes> {
		if (entries.some((e) => e.sessions === null))
			throw new Error('Renseignez tous les souhaits, y compris les valeurs à zéro.');
		submitted = entries;
		return {
			...wishInitial,
			subjects: wishInitial.subjects.map((s) => ({
				...s,
				staff: s.staff.map((p) => ({
					...p,
					sessions:
						entries.find((e) => e.subject_id === s.id && e.user_id === p.id)?.sessions ?? null
				}))
			}))
		};
	}
	async function command(
		action: '' | '/calculate' | '/merge' | '/discard' | '/rollback',
		publication?: NonNullable<RevisionView['pending_publications']>[number]
	): Promise<void> {
		if (busy) return;
		if (action === '/calculate' && !(await editor?.save())) return;
		busy = true;
		error = '';
		try {
			const wishes = submitted ?? branch?.wishes;
			const data =
				action === ''
					? {
							expected_source_revision: view.source_revision,
							subject_ids: selected,
							effective_on: effectiveOn,
							return_on: temporaryLeave ? returnOn : null
						}
					: action === '/calculate'
						? {
								expected_revision: branch?.revision,
								wishes,
								allow_moves: allowMoves,
								rooms: Object.fromEntries(subjects.map((s) => [s.id, rooms[s.id] ?? []])),
								effective_on: proposedDate
							}
						: action === '/merge'
							? {
									expected_revision: branch?.revision,
									effective_on: branch?.effective_on,
									return_on: branch?.return_on ?? null,
									confirmed_live: true
								}
							: action === '/rollback'
								? {
										expected_revision: publication?.revision,
										revision_id: publication?.id
									}
								: { expected_revision: branch?.revision };
			await timetableCommand('kholloscope/' + year + '/revision' + action, 'POST', data);
			await refresh();
			confirming = false;
			await invalidateAll();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Action impossible.';
		} finally {
			busy = false;
		}
	}
	function sessionLabel(session: GeneratedSession | null): string {
		if (!session) return '—';
		const day = new Date(session.day + 'T00:00:00Z').toLocaleDateString('fr-FR', {
			weekday: 'long',
			timeZone: 'UTC'
		});
		const clock = (seconds: number): string =>
			String(Math.floor(seconds / 3600)).padStart(2, '0') +
			':' +
			String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
		return (
			day +
			' ' +
			clock(session.start) +
			'–' +
			clock(session.end) +
			' · ' +
			(catalog.teachers.find((t) => t.id === session.teacher_id)?.name ??
				'Intervenant ' + session.teacher_id) +
			' · ' +
			(catalog.rooms.find((r) => r.id === session.room_id)?.name ?? 'Salle ' + session.room_id)
		);
	}
</script>

<svelte:window
	onbeforeunload={(event) => {
		if (dirty || busy) {
			event.preventDefault();
			event.returnValue = '';
		}
	}}
/>

<section aria-label="Révision du kholloscope" aria-busy={busy}>
	{#if view.problems?.length}
		<div class="notification is-warning is-light" role="alert">
			<h2 class="title is-5">Conflits détectés</h2>
			<ul>
				{#each view.problems as problem, index (problem.kind + '-' + index)}<li>
						{problem.message}
					</li>{/each}
			</ul>
		</div>
	{:else}<p class="notification is-success is-light" role="status">Aucun conflit détecté.</p>{/if}
	{#if error}<p class="notification is-danger is-light" role="alert">{error}</p>{/if}

	{#if view.pending_publications?.length}
		<div class="workspace-panel">
			<h2 class="title is-4">Révisions publiées en attente de prise d’effet</h2>
			{#each view.pending_publications as publication (publication.id)}
				<div class="publication-row">
					<span
						>Prise d’effet le <strong>{publication.effective_on}</strong>{publication.return_on
							? ' · Retour le ' + publication.return_on
							: ''}</span
					>
					<button
						class="button is-danger is-light"
						title={publication.can_rollback
							? 'Restaurer la version précédente'
							: 'Cette ancienne publication ne dispose pas de sauvegarde permettant une annulation sûre.'}
						disabled={busy || !canWrite || !publication.can_rollback}
						onclick={() => {
							if (
								window.confirm('Annuler cette publication et restaurer le calendrier précédent ?')
							)
								void command('/rollback', publication);
						}}>Annuler la publication</button
					>
				</div>
			{/each}
		</div>
	{/if}

	{#if !branch || branch.closed}
		<form
			class="workspace-panel"
			onsubmit={(event) => {
				event.preventDefault();
				void command('');
			}}
		>
			<h2 class="title is-4">Créer une proposition</h2>
			<fieldset disabled={busy || !canWrite}>
				<legend class="label">Matières à réviser ensemble</legend>
				<div class="subject-options">
					{#each view.subjects as subject (subject.id)}<div
							class="subject-option"
							style:--subject-color={subject.color}
						>
							<button
								type="button"
								class="subject-choice"
								aria-label={subject.name}
								aria-pressed={selected.includes(subject.id)}
								onclick={() =>
									(selected = selected.includes(subject.id)
										? selected.filter((id) => id !== subject.id)
										: [...selected, subject.id])}
							>
								<Icon name={subject.icon ?? 'book'} size={16} />
							</button><span>{subject.name}</span>
						</div>{/each}
				</div>
				<label class="label" for="revision-date"
					>Prise d’effet · lundi à minuit (Europe/Paris)</label
				>
				<input
					class="input date-input"
					id="revision-date"
					type="date"
					min={view.next_monday}
					required
					bind:value={effectiveOn}
				/>
				<p class="help mb-4">
					Le lundi suivant est proposé. Toutes les séances précédant la prise d’effet sont
					conservées.
				</p>
				<label class="checkbox mb-4"
					><input type="checkbox" bind:checked={temporaryLeave} /> Congé temporaire avec retour prévu</label
				>
				{#if temporaryLeave}
					<label class="label" for="revision-return">Retour · lundi à minuit (Europe/Paris)</label>
					<input
						class="input date-input"
						id="revision-return"
						type="date"
						required
						min={effectiveOn}
						bind:value={returnOn}
					/>
				{/if}
				<div class="step-actions">
					<button
						class="button is-primary"
						disabled={!selected.length ||
							!isRevisionMonday(effectiveOn) ||
							effectiveOn < view.next_monday ||
							(temporaryLeave && (!isRevisionMonday(returnOn) || returnOn <= effectiveOn))}
						>Créer la proposition préremplie</button
					>
				</div>
			</fieldset>
		</form>
	{:else}
		<div class="workspace-panel">
			<h2 class="title is-4">Proposition à partir du {branch.effective_on}</h2>
			{#if branch.stale}<p class="notification is-warning is-light">
					Les données ont changé. Abandonnez cette proposition et recréez-la.
				</p>{/if}
			{#if expired}
				<p class="notification is-warning is-light">
					La date de prise d’effet est dépassée. Choisissez un nouveau lundi et recalculez la
					proposition.
				</p>
				<label class="label" for="revised-date">Nouvelle prise d’effet</label>
				<input
					id="revised-date"
					class="input date-input"
					type="date"
					min={view.next_monday}
					bind:value={proposedDate}
					disabled={busy || active || !canWrite}
				/>
			{/if}
			{#key branch.revision}
				<KholleWishes
					guardNavigation={false}
					bind:this={editor}
					initial={wishInitial}
					{needs}
					saveEntries={saveWishes}
					startEditing
					canWrite={canWrite && !busy && !active && !branch.stale}
					ondirty={(value) => (editorDirty = value)}
					onvalidity={(value) => (editorValid = value)}
				>
					{#snippet subjectExtras(subject)}
						<KholleRoomSelection
							{subject}
							rooms={view.rooms ?? catalog.rooms}
							selected={rooms[subject.id] ?? []}
							disabled={busy || active || !canWrite || branch.stale}
							showHeading
							onselected={(ids) => (rooms = { ...rooms, [subject.id]: ids })}
						/>
					{/snippet}
				</KholleWishes>
			{/key}
			<fieldset disabled={busy || active || !canWrite || branch.stale}>
				<label class="checkbox"
					><input type="checkbox" bind:checked={allowMoves} /> Autoriser les déplacements dans la même
					semaine si nécessaire</label
				>
			</fieldset>
			<div class="step-actions">
				<button
					class="button is-primary"
					disabled={busy ||
						active ||
						!canWrite ||
						branch.stale ||
						!editorValid ||
						!isRevisionMonday(proposedDate) ||
						subjects.some((s) => !rooms[s.id]?.length)}
					onclick={() => command('/calculate')}>Calculer la proposition</button
				>
			</div>
		</div>

		<div class="workspace-panel">
			<h2 class="title is-4">Journal du calcul</h2>
			<pre
				bind:this={logElement}
				class="solver-log"
				role="log"
				aria-label="Journal du calcul"
				aria-live="polite">{logText || 'Aucun calcul lancé.'}</pre>
		</div>

		{#if branch.result}
			<div class="workspace-panel">
				<h2 class="title is-4">Modifications proposées</h2>
				{#if !changes.length}<p>Aucune séance à modifier.</p>{:else}
					<div class="table-container">
						<table class="table is-fullwidth">
							<thead
								><tr><th>Matière et groupe</th><th>Avant</th><th>Après</th><th>Période</th></tr
								></thead
							>
							<tbody
								>{#each changes as change (change.key)}
									{@const session = change.after ?? change.before!}
									{@const subject = view.subjects.find((s) => s.id === session.subject_id)}
									<tr style:--subject-color={subject?.color ?? '#808080'}>
										<th
											>{#if subject}<SubjectTag {subject} />{/if}
											<div>
												{catalog.calendars.find((c) => c.id === session.calendar_id)?.name ?? ''} · Groupe
												{session.group}
											</div></th
										>
										<td>{sessionLabel(change.before)}</td>
										<td
											><strong
												>{change.after
													? revisionChange(change.before, change.after)
													: 'Retrait du groupe inactif'}</strong
											><br />{change.after
												? sessionLabel(change.after)
												: 'Séances futures retirées'}</td
										>
										<td
											>{change.count} séance{change.count > 1 ? 's' : ''}<br
											/>{change.first}{change.last !== change.first ? ' au ' + change.last : ''}</td
										>
									</tr>
								{/each}</tbody
							>
						</table>
					</div>
				{/if}
				<h3 class="title is-5 mt-5">Service calculé sur la période restante</h3>
				{#each subjects as subject (subject.id)}
					<article class="subject-panel" style:--subject-color={subject.color}>
						<header><SubjectTag {subject} /></header>
						<div class="table-container">
							<table class="table is-fullwidth">
								<thead><tr><th>Intervenant</th><th>Séances à assurer</th></tr></thead>
								<tbody
									>{#each subject.staff as person (person.id)}<tr
											><th>{person.name}</th><td
												>{branch.future_service[subject.id]?.[person.id] ?? 0}</td
											></tr
										>{/each}</tbody
								>
							</table>
						</div>
					</article>
				{/each}
				<div class="step-actions">
					<button
						class="button is-danger"
						disabled={busy || dirty || active || expired || branch.stale || !canWrite}
						onclick={() => (confirming = true)}>Accepter et publier dans les agendas</button
					>
				</div>
				{#if dirty}<p class="help">Recalculez pour actualiser ces résultats.</p>{/if}
			</div>
		{/if}
		<div class="step-actions">
			<button
				class="button is-light"
				disabled={busy || !canWrite}
				onclick={() => {
					if (window.confirm('Abandonner cette proposition ?')) void command('/discard');
				}}>Abandonner la proposition</button
			>
		</div>
	{/if}
</section>

{#if confirming && branch}
	<Modal title="Confirmer la publication" {busy} onclose={() => (confirming = false)}>
		<p>
			Publier cette révision à partir du <strong>{branch.effective_on}</strong>{branch.return_on
				? ', avec retour le ' + branch.return_on
				: ''} ?
		</p>
		<p class="mt-3">Les séances précédentes sont conservées.</p>
		<button
			class="button is-danger mt-4"
			disabled={busy || dirty || expired}
			onclick={() => command('/merge')}>Confirmer la publication</button
		>
	</Modal>
{/if}

<style>
	section {
		min-width: 0;
	}
	fieldset {
		border: 0;
		padding: 0;
		min-width: 0;
	}
	.subject-options,
	.publication-row {
		display: flex;
		gap: 1rem;
		flex-wrap: wrap;
		margin: 1rem 0 1.5rem;
		align-items: center;
	}
	.publication-row {
		justify-content: space-between;
	}
	.subject-option {
		display: flex;
		align-items: center;
		gap: 0.65rem;
	}
	.subject-choice {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 2rem;
		height: 2rem;
		border-radius: 0.6rem;
		border: var(--border-thin);
		color: var(--color-muted);
		background: var(--color-surface);
		cursor: pointer;
	}
	.subject-choice[aria-pressed='true'] {
		color: var(--color-ink);
		background: color-mix(in srgb, var(--subject-color) 28%, var(--color-surface));
		border-color: var(--subject-color);
		box-shadow: inset 0 0 0 1px var(--subject-color);
	}
	.subject-choice:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 3px;
	}
	.subject-choice:disabled {
		cursor: default;
	}
	.date-input {
		max-width: 18rem;
		margin-bottom: 1rem;
	}
	.subject-panel {
		border: var(--border-thin);
		border-top: 3px solid var(--subject-color);
		border-radius: var(--radius-panel);
		overflow: hidden;
		margin: 1rem 0;
	}
	.subject-panel header {
		display: flex;
		gap: 1rem;
		padding: 1rem;
		background: color-mix(in srgb, var(--subject-color) 7%, var(--color-surface));
	}
	table {
		font-size: 0.85rem;
	}
	th,
	td {
		padding: 0.85rem;
		vertical-align: middle;
	}
	tbody tr {
		background: color-mix(in srgb, var(--subject-color, #808080) 5%, var(--color-surface));
	}
	.solver-log {
		max-height: 20rem;
		overflow: auto;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		background: var(--color-paper);
		color: var(--color-ink);
		font-size: 0.75rem;
	}
	li + li {
		margin-top: 0.75rem;
	}
</style>
