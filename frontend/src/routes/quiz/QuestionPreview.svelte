<script lang="ts">
	import { resolve } from '$app/paths';
	import type { QuizPreview, QuizSubject } from '#lib/quiz';
	import { quizAction } from './api';
	import QuizMath from '#lib/components/QuizMath.svelte';
	import FormattedText from '#lib/components/lessons/FormattedText.svelte';
	import Icon from '#lib/components/Icon.svelte';

	let {
		subject,
		question,
		draft = false
	}: { subject: QuizSubject; question: QuizPreview; draft?: boolean } = $props();
	const subjectParams = $derived({ subjectId: String(subject.id) });
	let choices = $state<number[]>([]);
	let text = $state('');
	let correct = $state<boolean | null>(null);
	let failure = $state('');
	let busy = $state(false);

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (draft) return;
		busy = true;
		correct = null;
		failure = '';
		try {
			const result = await quizAction<{ correct: boolean }>('preview', subject.id, question.id, {
				version: question.version,
				answer: question.kind === 'choice' ? choices : text
			});
			correct = result.correct;
		} catch (cause) {
			failure = cause instanceof Error ? cause.message : 'La validation a échoué.';
		} finally {
			busy = false;
		}
	}
</script>

<div class="box">
	<p class="is-size-7 mb-2">Aperçu élève</p>
	<h1 class="title is-4">{question.title}</h1>
	{#if question.statement}
		<div class="mb-4">
			<FormattedText text={question.statement} color={subject.color} headings={false} />
		</div>
	{/if}
	{#if question.image}
		<img class="question-image mb-4" src={question.image} alt={question.image_alt} />
	{/if}
	<p class="mb-4 has-text-weight-semibold"><QuizMath text={question.prompt} /></p>

	<form onsubmit={submit}>
		{#if question.kind === 'choice'}
			<fieldset
				class="field"
				disabled={busy}
				onchange={() => {
					correct = null;
					failure = '';
				}}
			>
				<legend class="label">Sélectionnez la ou les bonnes réponses</legend>
				{#each question.options as option, index (index)}
					<label class="checkbox is-flex gap mb-2">
						<input type="checkbox" value={index} bind:group={choices} />
						<QuizMath text={option} />
					</label>
				{/each}
			</fieldset>
		{:else}
			<div class="field">
				<label class="label" for="preview-answer">Votre réponse</label>
				<input
					class="input"
					id="preview-answer"
					maxlength="300"
					required
					disabled={busy}
					bind:value={text}
					oninput={() => {
						correct = null;
						failure = '';
					}}
				/>
				{#if question.kind === 'number'}<p class="help">Exemples de format · 0,5 ou 1/2</p>{/if}
			</div>
		{/if}
		{#if failure}<p class="notification is-danger is-light" role="alert">{failure}</p>{/if}
		{#if correct !== null}
			<p
				class={correct ? 'notification is-success is-light' : 'notification is-warning is-light'}
				class:celebrate={correct}
				role="status"
			>
				{#if correct}<span class="answer-check"><Icon name="check" size={18} /></span>{/if}
				{correct ? 'Bonne réponse.' : 'Réponse incorrecte.'}
			</p>
		{/if}
		<div class="buttons">
			<button
				class="button is-primary"
				class:is-loading={busy}
				type="submit"
				disabled={draft || busy || (question.kind === 'choice' ? !choices.length : !text.trim())}
				>Valider</button
			>
			{#if !draft && subject.can_edit}<a
					class="button"
					href={resolve(`/quiz/[subjectId]?modifier=${question.id}`, subjectParams)}>Modifier</a
				>{/if}
			{#if !draft}<a class="button is-light" href={resolve('/quiz/[subjectId]', subjectParams)}
					>Retour aux fiches</a
				>
			{/if}
		</div>
	</form>
</div>

<style>
	.answer-check {
		display: inline-flex;
		vertical-align: middle;
		margin-inline-end: 0.4rem;
	}

	@media (prefers-reduced-motion: no-preference) {
		.celebrate .answer-check {
			animation: answer-pop 450ms ease-out both;
		}
	}

	@keyframes answer-pop {
		0% {
			opacity: 0;
			transform: scale(0.3) rotate(-25deg);
		}
		65% {
			opacity: 1;
			transform: scale(1.4) rotate(8deg);
		}
		100% {
			opacity: 1;
			transform: scale(1);
		}
	}

	.gap {
		gap: 0.6rem;
		align-items: baseline;
	}
	.question-image {
		display: block;
		margin-inline: auto;
		max-height: 24rem;
		object-fit: contain;
	}
</style>
