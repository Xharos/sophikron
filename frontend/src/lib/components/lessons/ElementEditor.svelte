<script lang="ts">
	import { untrack } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import {
		elementLabels,
		lessonCommand,
		type ElementKind,
		type LessonDetail,
		type LessonElement,
		type ScheduleMode
	} from '#lib/lessons';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import TextEditor from '../TextEditor.svelte';
	import ResourcePolicy from './ResourcePolicy.svelte';
	let {
		lesson,
		element = null,
		kind,
		parent,
		rowIndex = null,
		columnIndex = null,
		onsaved,
		onclose
	}: {
		lesson: LessonDetail;
		element?: LessonElement | null;
		kind: ElementKind;
		parent: LessonElement | null;
		rowIndex?: number | null;
		columnIndex?: number | null;
		onsaved: (lesson: LessonDetail) => void;
		onclose: () => void;
	} = $props();
	const snapshot = untrack(() => ({ element, today: lesson.today, version: lesson.version }));
	let title = $state(snapshot.element?.title ?? '');
	let body = $state(snapshot.element?.body ?? '');
	let mode = $state<ScheduleMode>(snapshot.element?.schedule_mode ?? 'inherit');
	let start = $state(snapshot.element?.starts_on ?? snapshot.today);
	const schoolEnd = `${Number(snapshot.today.slice(0, 4)) + (snapshot.today.slice(5, 7) >= '09' ? 1 : 0)}-08-31`;
	let end = $state(snapshot.element?.ends_on ?? schoolEnd);
	let audience = $state<'students' | 'staff'>(snapshot.element?.audience ?? 'students');
	let rows = $state(1);
	let columns = $state(['']);
	let busy = $state(false);
	let message = $state('');
	const initialVersion = snapshot.version;

	const structural = $derived(kind === 'section' || kind === 'subsection' || kind === 'table');
	const scheduled = $derived(kind === 'youtube' && parent?.effective_audience !== 'staff');
	const initial = untrack(() =>
		JSON.stringify({ title, body, mode, start, end, audience, rows, columns })
	);
	const dirty = $derived(
		JSON.stringify({ title, body, mode, start, end, audience, rows, columns }) !== initial
	);
	function close(): void {
		if (!dirty || window.confirm('Abandonner les modifications de cet élément ?')) onclose();
	}
	beforeNavigate((navigation) => {
		if (!busy && dirty && !window.confirm('Abandonner les modifications de cet élément ?'))
			navigation.cancel();
	});
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			const data = {
				title,
				audience: kind === 'section' ? audience : 'students',
				body: structural ? '' : body,
				schedule_mode: scheduled ? mode : 'inherit',
				starts_on: scheduled && mode !== 'inherit' ? start : null,
				ends_on: scheduled && mode === 'range' ? end : null,
				expected_version: initialVersion,
				...(!element
					? {
							kind,
							parent_id: parent?.id ?? null,
							row_index: rowIndex,
							column_index: columnIndex,
							...(kind === 'table' ? { table_rows: rows, table_columns: columns } : {})
						}
					: {})
			};
			onsaved(
				await lessonCommand<LessonDetail>(element ? 'updateElement' : 'addElement', {
					lessonId: lesson.id,
					elementId: element?.id,
					data
				})
			);
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window
	onbeforeunload={(event) => {
		if (dirty && !busy) {
			event.preventDefault();
			event.returnValue = '';
		}
	}}
/>
<Modal
	title={`${element ? 'Modifier' : 'Ajouter'} · ${elementLabels[kind]}`}
	description={parent ? `Dans « ${parent.title} »` : 'Au premier niveau du cours'}
	{busy}
	onclose={close}
>
	<form onsubmit={save}>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<div class="field">
			<label class="label" for="element-title">{structural ? 'Titre' : 'Titre facultatif'}</label
			><input
				id="element-title"
				class="input"
				bind:value={title}
				maxlength="200"
				required={structural}
			/>
		</div>
		{#if !structural}
			<div class="field">
				<label class="label" for="element-body"
					>{kind === 'youtube' ? 'Lien YouTube' : 'Texte'}</label
				>
				{#if kind === 'text'}
					<TextEditor
						id="element-body"
						bind:value={body}
						color={lesson.color}
						disabled={busy}
						required
					/>
				{:else}<input
						id="element-body"
						type="url"
						class="input"
						bind:value={body}
						placeholder="https://www.youtube.com/watch?v=…"
						required
						maxlength="1000"
					/>
					<p class="help">
						Lien HTTPS YouTube ou youtu.be. Aucun code d’intégration n’est nécessaire.
					</p>{/if}
			</div>
		{/if}
		{#if kind === 'table' && !element}
			<div class="field">
				<label class="label" for="table-rows">Nombre de lignes</label><input
					id="table-rows"
					class="input"
					type="number"
					min="1"
					max="20"
					bind:value={rows}
					required
				/>
			</div>
			{#each columns.keys() as index (index)}<div class="field">
					<label class="label" for={`table-column-${index}`}>Titre de la colonne {index + 1}</label
					><input
						id={`table-column-${index}`}
						class="input"
						bind:value={columns[index]}
						maxlength="100"
						required
					/>
				</div>{/each}
			<button
				class="button is-light is-small"
				type="button"
				disabled={columns.length >= 6}
				onclick={() => (columns = [...columns, ''])}>Ajouter une colonne</button
			>
		{/if}
		<ResourcePolicy bind:mode bind:start bind:end bind:audience {parent} {kind} disabled={busy} />
		<div class="dialog-actions">
			<button class="button is-light" type="button" onclick={close} disabled={busy}>Annuler</button
			><button
				class="button is-primary"
				type="submit"
				class:is-loading={busy}
				disabled={busy || (scheduled && mode === 'range' && end < start)}
				><Icon name="save" />Enregistrer</button
			>
		</div>
	</form>
</Modal>
