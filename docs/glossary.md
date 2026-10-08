# Planning glossary

| Term | Meaning in this project |
|---|---|
| PR | Purchase requisition: a request for a product, quantity, market and delivery date |
| PO | Purchase order issued to a supplier |
| RDD | Requested delivery date |
| Manufacturing lead time | Days required to manufacture the product |
| Transportation lead time | Days required to transport the product |
| Release date | RDD minus manufacturing and transportation lead times |
| Lot | A group of purchase requisitions planned together |
| MOQ | Minimum order quantity: configured as 300 units per article and market |
| MPQ | Minimum production quantity per article and factory within a planning run: 1,200 for apparel and 2,400 for footwear |
| Certified factory | A factory approved to manufacture an article |
| Primary factory | The first factory considered for an article |
| Backup factory | An alternative factory considered under the routing rules |
| Piggyback | Bringing whole future requisitions forward to help meet a quantity minimum |
| Capacity ledger | Planned units allocated by factory and production week |
| NSV | Net sales value associated with sales orders |
| Manual override | A saved planner decision applied on top of the automatic plan |

## Important distinctions

- A purchase requisition is a request; a purchase order is a supplier order.
- BOUGHT is an internal planning outcome. It does not prove that an order was transmitted to a supplier.
- Sales value at risk is not the same as confirmed financial loss.
- Passing demand accounting checks does not prove that a factory schedule is feasible.
