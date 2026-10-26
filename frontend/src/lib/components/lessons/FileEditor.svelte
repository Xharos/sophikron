<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import {
		lessonCommand,
		documentLabel,
		type LessonDetail,
		type LessonElement,
		type ScheduleMode
	} from '#lib/lessons';
	import Modal from '../Modal.svelte';
	import ResourcePolicy from './ResourcePolicy.svelte';
	import FileDropzone from './FileDropzone.svelte';
	import Icon from '../Icon.svelte';
	let {
		lesson,
		element = null,
		parent,
		rowIndex = null,
		columnIndex = null,
		onsaved,
		onclose
	}: {
		lesson: LessonDetail;
		element?: LessonElement | null;
		parent: LessonElement;
		rowIndex?: number | null;
		columnIndex?: number | null;
		onsaved: (lesson: LessonDetail) => void;
		onclose: () => void;
	} = $props();
	const snapshot = untrack(() => ({ element, today: lesson.today, version: lesson.version }));
	let title = $state(
		snapshot.element
			? documentLabel(snapshot.element.title, snapshot.element.file?.extension ?? '')
			: ''
	);
	let mode = $state<ScheduleMode>(snapshot.element?.schedule_mode ?? 'inherit');
	let start = $state(snapshot.element?.starts_on ?? snapshot.today);
	let end = $state(snapshot.element?.ends_on ?? snapshot.today);
	let audience = $state<'students' | 'staff'>(snapshot.element?.audience ?? 'students');
	let selected = $state<File | null>(null);
	let limits = $state<Record<string, number> | null>(null);
	let message = $state('');
	let busy = $state(false);
	let progress = $state(0);
	let transfer: XMLHttpRequest | null = null;
	let uploadId: string | null = null;
	const initial = untrack(() => JSON.stringify({ title, mode, start, end, audience }));
	const dirty = $derived(
		selected !== null || JSON.stringify({ title, mode, start, end, audience }) !== initial
	);
	const extension = $derived(selected?.name.split('.').at(-1)?.toLowerCase() ?? '');
	const scheduled = $derived(parent.effective_audience !== 'staff');
	function selectFile(file: File): void {
		const previous = selected
			? documentLabel(selected.name, selected.name.split('.').at(-1) ?? '')
			: '';
		if (!title || title === previous)
			title = documentLabel(file.name, file.name.split('.').at(-1) ?? '');
		selected = file;
	}
	const limit = $derived(limits?.[extension]);
	const tooLarge = $derived(selected !== null && limit !== undefined && selected.size > limit);
	const invalid = $derived(
		selected !== null && limits !== null && (!limit || selected.size === 0 || tooLarge)
	);
	onMount(() => {
		const controller = new AbortController();
		void fetch('/lessons/options?resource=documentLimits', { signal: controller.signal })
			.then(async (response) => {
				if (!response.ok) throw new Error('Les limites de dépôt ne sont pas disponibles.');
				limits = (await response.json()).types;
			})
			.catch((cause: Error) => {
				if (!controller.signal.aborted) message = cause.message;
			});
		return () => {
			controller.abort();
			transfer?.abort();
		};
	});
	function close(): void {
		if (!dirty || window.confirm('Abandonner ce document et ses modifications ?')) onclose();
	}
	beforeNavigate((navigation) => {
		if ((busy || dirty) && !window.confirm('Abandonner le document en cours ?'))
			navigation.cancel();
	});
	async function send(file: File, id: string): Promise<LessonDetail> {
		return new Promise((resolve, reject) => {
			const xhr = new XMLHttpRequest();
			transfer = xhr;
			xhr.open('POST', `/lessons/upload?lessonId=${lesson.id}&uploadId=${id}`);
			xhr.timeout = 360000;
			xhr.setRequestHeader('Content-Type', 'application/octet-stream');
			xhr.upload.onprogress = (event) => {
				if (event.lengthComputable) progress = Math.round((event.loaded / event.total) * 100);
			};
			xhr.onerror = () =>
				reject(new Error('Transfert interrompu. Actualisez le cours avant de réessayer.'));
			xhr.onabort = () => reject(new Error('Transfert annulé.'));
			xhr.ontimeout = () => reject(new Error('Le transfert a pris trop de temps.'));
			xhr.onload = () => {
				if ([401, 403].includes(xhr.status))
					window.dispatchEvent(new Event('lesson-access-revoked'));
				try {
					const result = JSON.parse(xhr.responseText);
					if (xhr.status >= 200 && xhr.status < 300) resolve(result);
					else reject(new Error(result.message || 'Le document a été refusé.'));
				} catch {
					reject(new Error('Réponse de transfert invalide. Actualisez le cours.'));
				}
			};
			xhr.send(file);
		});
	}
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		progress = 0;
		const data = {
			title,
			body: '',
			audience: 'students',
			schedule_mode: scheduled ? mode : 'inherit',
			starts_on: scheduled && mode !== 'inherit' ? start : null,
			ends_on: scheduled && mode === 'range' ? end : null,
			expected_version: snapshot.version
		};
		try {
			if (selected) {
				const reservation = await lessonCommand<{ upload_id: string }>('reserveUpload', {
					lessonId: lesson.id,
					data: {
						...data,
						filename: selected.name,
						size_bytes: selected.size,
						parent_id: parent.id,
						element_id: element?.id ?? null,
						row_index: rowIndex,
						column_index: columnIndex
					}
				});
				uploadId = reservation.upload_id;
				onsaved(await send(selected, uploadId));
			} else if (element)
				onsaved(
					await lessonCommand<LessonDetail>('updateElement', {
						lessonId: lesson.id,
						elementId: element.id,
						data
					})
				);
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			if (uploadId) {
				void lessonCommand('cancelUpload', { lessonId: lesson.id, uploadId }).catch(() => {});
				uploadId = null;
			}
			transfer = null;
			busy = false;
		}
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
<Modal
	title={element ? 'Modifier le document' : 'Ajouter un document'}
	description={`Dans « ${parent.title} »`}
	{busy}
	onclose={close}
>
	<form onsubmit={save}>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<FileDropzone
			file={selected}
			disabled={busy || !limits}
			accept={limits
				? Object.keys(limits)
						.map((ext) => '.' + ext)
						.join(',')
				: ''}
			onselect={selectFile}
		/>
		<details class="mt-2">
			<summary class="muted text-small">Formats et limites</summary>
			<p class="help">
				JPG/PNG : 10 Mio · PDF/DOCX/XLSX : 25 Mio · ZIP : 50 Mio · Python : 1 Mio. Les fichiers
				Python sont uniquement téléchargeables.
			</p>
		</details>
		{#if element?.file}<p class="help">Fichier actuel : {element.file.original_name}</p>{/if}
		{#if invalid}<p class="help is-danger" role="alert">
				{tooLarge
					? 'Ce fichier dépasse la taille autorisée.'
					: 'Ce fichier est vide ou son format n’est pas autorisé.'}
			</p>{/if}
		{#if tooLarge && extension === 'pdf'}<p class="help">
				<a
					href="https://www.ilovepdf.com/fr/compresser_pdf"
					target="_blank"
					rel="noopener noreferrer">Compresser le PDF avec iLovePDF</a
				> — service tiers ; privilégiez un outil local pour les données personnelles.
			</p>{/if}
		<div class="field mt-4">
			<label class="label" for="document-title">Nom affiché dans le cours</label><input
				id="document-title"
				class="input"
				bind:value={title}
				maxlength="200"
				required
				disabled={busy}
			/>
		</div>
		<ResourcePolicy
			bind:mode
			bind:start
			bind:end
			bind:audience
			{parent}
			kind="file"
			disabled={busy}
		/>
		{#if busy}<progress class="progress is-primary mt-4" max="100" value={progress}
				>{progress} %</progress
			>
			<p role="status">
				{progress === 100 ? 'Vérification du fichier…' : `Transfert : ${progress} %`}
			</p>{/if}
		<div class="dialog-actions">
			<button
				class="button is-light"
				type="button"
				onclick={() => {
					if (busy) transfer?.abort();
					else close();
				}}>{busy ? 'Annuler le transfert' : 'Annuler'}</button
			><button
				class="button is-primary"
				type="submit"
				disabled={busy ||
					!limits ||
					invalid ||
					(!element && !selected) ||
					(scheduled && mode === 'range' && end < start)}><Icon name="save" />Enregistrer</button
			>
		</div>
	</form>
</Modal>
