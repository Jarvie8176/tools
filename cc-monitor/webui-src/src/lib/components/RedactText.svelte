<script lang="ts">
  import { isRedacted } from "../format";
  // Renders free text; a server-redacted field ([redacted]) shows a masked block. Svelte escapes
  // the text interpolation by construction (the raw-HTML directive is never used anywhere in this
  // codebase — enforced by a source lint) so a hostile prompt/name cannot inject markup.
  let { text }: { text: string | null } = $props();
</script>
{#if isRedacted(text)}<span class="mono" style="color:var(--t4);letter-spacing:1px">▓▓▓▓▓▓</span>{:else}{text ?? ""}{/if}
