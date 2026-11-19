<script lang="ts">
	import { lessonCommand, type LessonDetail, type LessonElement } from '#lib/lessons';
	import Icon from '../Icon.svelte';
	import Modal from '../Modal.svelte';
	import QuizMath from '../QuizMath.svelte';
	import ResourceBody from './ResourceBody.svelte';
	import FormattedText from './FormattedText.svelte';
	import LessonQuizResults from './LessonQuizResults.svelte';

	type Card = {
		title: string;
		statement: string;
		prompt: string;
		image: string | null;
		image_alt: string;
		kind: 'choice' | 'text' | 'number';
		options: string[];
	};
	type Progress = { completed: number; total: number };
	type Passage = Progress & {
		revision: number;
		card: Card | null;
		correct: boolean | null;
		order: number[] | null;
	};

	let { item, lesson, editing }: { item: LessonElement; lesson: LessonDetail; editing: boolean } =
		$props();
	let progress = $state<(Progress & { started: boolean }) | null>(null);
	const current = $derived(progress ?? item.quiz_progress);
	const finished = $derived(!!current && current.completed === current.total);
	const action = $derived(finished ? 'Recommencer' : current?.started ? 'Reprendre' : 'Commencer');
	let lastReplayOrder: number[] | null = null;
	let passage = $state<Passage | null>(null);
	let selected = $state<number[]>([]);
	let response = $state('');
	let busy = $state(false);
	let message = $state('');
	let showResults = $state(false);
	const answerId = $props.id();

	function request<T>(command: string, data: object): Promise<T> {
		return lessonCommand<T>(command, { lessonId: lesson.id, elementId: item.id, data });
	}

	function clearAnswer(): void {
		selected = [];
		response = '';
	}

	async function open(replay: boolean): Promise<void> {
		message = '';
		busy = true;
		try {
			passage = await request<Passage>('quizStart', {
				replay,
				previous_order: replay ? lastReplayOrder : null
			});
			if (passage.order) lastReplayOrder = passage.order;
			if (!replay) progress = { completed: passage.completed, total: passage.total, started: true };
			clearAnswer();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!passage?.card || busy) return;
		const answer = passage.card.kind === 'choice' ? selected : response;
		message = '';
		busy = true;
		try {
			if (passage.order) {
				const { correct } = await request<{ correct: boolean }>('quizReplay', {
					index: passage.order[passage.completed],
					answer
				});
				const step = passage.completed + Number(correct);
				const card = !correct
					? passage.card
					: step === passage.total
						? null
						: (await request<{ card: Card }>('quizReplay', { index: passage.order[step] })).card;
				passage = { ...passage, completed: step, card, correct };
			} else {
				passage = await request<Passage>('quizAnswer', { revision: passage.revision, answer });
				progress = { completed: passage.completed, total: passage.total, started: true };
			}
			clearAnswer();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

{#if current}
	<ResourceBody
		{item}
		lessonId={lesson.id}
		color={lesson.color}
		staffView={lesson.staff_view}
		quizAction={action}
		quizProgress={current}
		onquiz={() => open(finished)}
		disabled={busy}
	/>
	{#if message && !passage}<p class="help is-danger" role="alert">{message}</p>{/if}
{/if}
{#if lesson.can_edit && !editing && item.effective_audience !== 'staff'}
	<button
		class="button is-small is-light mt-2"
		type="button"
		aria-expanded={showResults}
		onclick={() => (showResults = !showResults)}
		>{showResults ? 'Masquer les résultats' : 'Résultats du quiz'}</button
	>
	{#if showResults}<LessonQuizResults lessonId={lesson.id} elementId={item.id} />{/if}
{/if}

{#if passage}
	<Modal
		title={item.title}
		description={passage.order ? 'Entraînement libre' : 'Premier passage'}
		{busy}
		onclose={() => {
			passage = null;
			message = '';
		}}
	>
		<p class="mb-3">{passage.completed}/{passage.total} fiches résolues</p>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		{#if passage.correct !== null}
			<p
				role="status"
				class={passage.correct
					? 'notification is-success is-light'
					: 'notification is-warning is-light'}
			>
				{passage.correct ? 'Bonne réponse.' : 'Réponse incorrecte. Réessaie.'}
			</p>
		{/if}
		{#if passage.card}
			{@const card = passage.card}
			<h3 class="title is-5">{card.title}</h3>
			{#if card.statement}<div class="mb-3">
					<FormattedText text={card.statement} color={lesson.color} headings={false} />
				</div>{/if}
			{#if card.image}<img class="question-image mb-3" src={card.image} alt={card.image_alt} />{/if}
			<p class="has-text-weight-semibold mb-3"><QuizMath text={card.prompt} /></p>
			<form onsubmit={submit}>
				{#if card.kind === 'choice'}
					<fieldset class="mb-3" disabled={busy}>
						<legend class="label">Sélectionne la ou les bonnes réponses</legend>
						{#each card.options as option, index (index)}
							<label class="checkbox is-block mb-2">
								<input type="checkbox" value={index} bind:group={selected} />
								<QuizMath text={option} />
							</label>
						{/each}
					</fieldset>
				{:else}
					<div class="field">
						<label class="label" for={answerId}>Ta réponse</label>
						<input
							class="input"
							id={answerId}
							bind:value={response}
							disabled={busy}
							maxlength="300"
							required
						/>
						{#if card.kind === 'number'}<p class="help">Exemples · 0,5 ou 1/2</p>{/if}
					</div>
				{/if}
				<button
					class="button is-primary"
					type="submit"
					class:is-loading={busy}
					disabled={busy || (card.kind === 'choice' ? !selected.length : !response.trim())}
					>Valider</button
				>
			</form>
		{:else}
			<p class="mb-3"><Icon name="check" /> Quiz terminé.</p>
			<button class="button is-primary" type="button" disabled={busy} onclick={() => open(true)}
				>Recommencer</button
			>
		{/if}
	</Modal>
{/if}

<style>
	.question-image {
		display: block;
		margin-inline: auto;
		max-height: 20rem;
		object-fit: contain;
	}
</style>
