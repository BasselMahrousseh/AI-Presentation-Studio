/**
 * pptx-composer-api
 *
 * Per AGENTS.md section 3 and 02_Solution_Architecture.md section 2.3:
 * "No model calls inside the composer." This service takes validated
 * SlideSpec/DeckSpec JSON as input and produces a PPTX artifact as output.
 * It never calls an AI model directly.
 */
 
const express = require('express');
const { composeDeck } = require('./lib/pptx-builder');
 
const app = express();
app.use(express.json({ limit: '10mb' }));
 
const PORT = process.env.PORT || 4000;
 
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'pptx-composer-api' });
});
 
/**
 * POST /compose
 * body: either { slides: SlideSpec[] } (a full deck) or a single
 * SlideSpec object directly (auto-wrapped into a one-slide deck).
 *
 * Returns the generated .pptx as a binary download. Composition warnings
 * and the object map are returned as base64-encoded JSON in response
 * headers (X-Composer-Warnings, X-Composer-Object-Map) for the PoC;
 * a real implementation should persist the full composition report
 * alongside the artefact, per section 2.4's output contract.
 */
app.post('/compose', (req, res) => {
  const body = req.body;
 
  const isDeckSpec = body && Array.isArray(body.slides);
  const isSlideSpec = body && typeof body === 'object' && Array.isArray(body.objects);
 
  if (!isDeckSpec && !isSlideSpec) {
    return res.status(400).json({
      error:
        'Request body must be either a DeckSpec with a "slides" array, or a single SlideSpec object with an "objects" array. See 06_Template_and_PPTX_Engineering.md section 6.4.',
    });
  }
 
  let result;
  try {
    result = composeDeck(body);
  } catch (err) {
    console.error('Composition failed:', err);
    return res.status(422).json({ error: 'Composition failed', detail: err.message });
  }
 
  const { pptx, warnings, objectMap } = result;
 
  pptx
    .write({ outputType: 'nodebuffer' })
    .then((buffer) => {
      res.setHeader(
        'Content-Type',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
      );
      res.setHeader('Content-Disposition', 'attachment; filename="deck.pptx"');
      res.setHeader('X-Composer-Warnings', Buffer.from(JSON.stringify(warnings)).toString('base64'));
      res.setHeader('X-Composer-Object-Map', Buffer.from(JSON.stringify(objectMap)).toString('base64'));
      res.send(buffer);
    })
    .catch((err) => {
      console.error('PPTX write failed:', err);
      res.status(500).json({ error: 'Failed to serialize PPTX', detail: err.message });
    });
});
 
app.listen(PORT, () => {
  console.log(`pptx-composer-api listening on http://localhost:${PORT}`);
});
 