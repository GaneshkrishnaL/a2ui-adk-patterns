/**
 * Mock "agent" - stands in for the ADK / A2A backend.
 *
 * In production this is replaced by an SSE / A2A client: the renderer POSTs the ActionPayload
 * (name, surfaceId, sourceComponentId, context, timestamp) to the agent, and the agent replies
 * with more A2UI messages. Here we answer locally so the round-trip is visible with no server.
 */
import type {ActionPayload} from '@a2ui/web_core/v0_9';
import type {A2uiMessage} from './scenarios';

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

export async function mockAgentRespond(
  action: ActionPayload,
  getData: (surfaceId: string, path: string) => unknown,
): Promise<A2uiMessage[]> {
  const {name, surfaceId} = action;
  await sleep(350); // simulated network + agent latency

  switch (name) {
    case 'follow': {
      const following = getData(surfaceId, '/followText') === 'Following ✓';
      const followers = Number(getData(surfaceId, '/followers') ?? 0);
      return [
        {version: 'v0.9', updateDataModel: {surfaceId, path: '/followText', value: following ? 'Follow' : 'Following ✓'}},
        {version: 'v0.9', updateDataModel: {surfaceId, path: '/followers', value: following ? followers - 1 : followers + 1}},
      ];
    }
    case 'open_stat': {
      const stat = String(action.context?.stat ?? '');
      return [
        {
          version: 'v0.9',
          updateDataModel: {
            surfaceId,
            path: '/bio',
            value: `You tapped **${stat}** - an agent could now stream a drill-down surface for it.`,
          },
        },
      ];
    }
    case 'message':
    case 'send_message': {
      // Agent creates a brand-new surface as a confirmation card.
      const id = `confirm_${Date.now()}`;
      const subject = action.context?.subject ? ` "${String(action.context.subject)}"` : '';
      return [
        {version: 'v0.9', createSurface: {surfaceId: id, catalogId: 'https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json'}},
        {
          version: 'v0.9',
          updateComponents: {
            surfaceId: id,
            components: [
              {id: 'root', component: 'Card', child: 'row'},
              {id: 'row', component: 'Row', align: 'center', children: ['ic', 'col']},
              {id: 'ic', component: 'Icon', name: 'check'},
              {id: 'col', component: 'Column', children: ['t', 'c']},
              {id: 't', component: 'Text', variant: 'h4', text: 'Message sent'},
              {id: 'c', component: 'Text', variant: 'caption', text: {path: '/detail'}},
            ],
          },
        },
        {version: 'v0.9', updateDataModel: {surfaceId: id, path: '/', value: {detail: `Delivered${subject} to ${String(action.context?.to ?? '@sarahchen')}.`}}},
      ];
    }
    default:
      return [];
  }
}
