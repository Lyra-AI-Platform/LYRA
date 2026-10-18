"""
COSHH AI — substance safety database.

Builds a full 16-section safety data sheet for any substance from public,
authoritative sources and adds the COSHH detail a classic SDS leaves out:

- PubChem (NIH) for GHS classification, first aid, firefighting, spills,
  handling and storage, PPE, physical properties, toxicology, ecology,
  disposal, transport and regulatory data, every line with its source.
- HSE EH40/2005 Table 1 for the legally binding UK workplace exposure limits.
- NIST Chemistry WebBook for full IR and mass spectra (JCAMP-DX), plus the
  NMR shifts, GC-MS peaks and GC retention indices that PubChem holds.
- Rule-based COSHH guidance (health surveillance, storage segregation,
  DSEAR, LEV, RPE, new and expectant mothers) derived from the H-statements
  and the EH40 notations, each with the regulation it comes from.

A compiled sheet is decision support. It is not a supplier's SDS: the
supplier's SDS for the actual product (mixtures, concentrations, glove
breakthrough times) still applies, and a competent person signs off the
COSHH assessment.
"""
