# Recyclability

Recyclability is generally defined as the percentage of the total material mass from a demolished bridge that can be recovered, processed, and returned to the production cycle for reuse.

$$
\text{Recyclability} = \frac{\text{Recovered material}}{\text{Total material}} \times 100
$$

In the software, the **total material quantity has already been entered in the previous input step**. Therefore, while defining recyclability, the user only needs to provide:

- Recyclability (%) of the material
- Scrap rate (₹ per recovered unit)

The software uses the previously entered material quantity to automatically calculate the recovered quantity and the corresponding scrap value.

For example:
- Total material quantity (entered previously) = 50 units
- Recyclability = 70%
- Scrap rate = ₹100 per recovered unit

$$
\text{Recovered material} = 50 \times \frac{70}{100} = 35 \text{ units}
$$

$$
\text{Total scrap value} = 35 \times 100 = \text{₹3,500}
$$

Therefore:
- Recovered material = 35 units
- Material lost = 15 units
- Total scrap value = ₹3,500