# Routine Inspection Cost

These are the costs corresponding to periodic (annual) inspection activities that are needed to maintain the functionality and load-carrying capacity of the bridge. This includes expenses for routine maintenance activities like resurfacing, repainting, and minor repairs.

$$RIC = PWF \times P_{ICS}$$

where:
- **$RIC$**: routine inspection cost
- **$PWF$**: present worth factor
- **$P_{ICS}$**: percentage of initial construction cost for routine inspection

PWF converts future periodic costs to present worth for life cycle cost estimation.

$$PWF = \sum_{i=1}^{\lfloor n/x \rfloor - 1} \frac{(1+f)^{ix}}{(1+r)^{ix}}$$

where:
- **$PWF$**: present worth factor
- **$f$**: inflation rate
- **$r$**: discount rate
- **$n$**: design life
- **$x$**: periodic interval